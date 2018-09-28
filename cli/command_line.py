'''This module implements a command line interface which allows gateway
devices to be  queried and manipulated.
'''

import getpass
import json
import logging
import os
import pathlib
import requests
import shlex
import shutil
import sys

from cmd import Cmd
from cli.column import column_print
from cli.gateway import Gateway

GOOD = logging.INFO + 1


def trim(docstring):
    '''Trims the leading spaces from docstring comments.

    From http://www.python.org/dev/peps/pep-0257/

    '''
    if not docstring:
        return ''
    # Convert tabs to spaces (following the normal Python rules)
    # and split into a list of lines:
    lines = docstring.expandtabs().splitlines()
    # Determine minimum indentation (first line doesn't count):
    indent = sys.maxsize
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            indent = min(indent, len(line) - len(stripped))
    # Remove indentation (first line is special):
    trimmed = [lines[0].strip()]
    if indent < sys.maxsize:
        for line in lines[1:]:
            trimmed.append(line[indent:].rstrip())
    # Strip off trailing and leading blank lines:
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    while trimmed and not trimmed[0]:
        trimmed.pop(0)
    # Return a single string:
    return '\n'.join(trimmed)


def word_len(word):
    """Returns the word lenght, minus any color codes."""
    if word[0] == '\x1b':
        return len(word) - 11   # 7 for color, 4 for no-color
    return len(word)


def print_cols(words, print_func, termwidth=79):
    '''Takes a single column of words, and prints it as multiple columns that
    will fit in termwidth columns.
    '''
    width = max([word_len(word) for word in words])
    nwords = len(words)
    ncols = max(1, (termwidth + 1) // (width + 1))
    nrows = (nwords + ncols - 1) // ncols
    for row in range(nrows):
        line = ''
        for i in range(row, nwords, nrows):
            word = words[i]
            if word[0] == '\x1b':
                line += '%-*s' % (width + 11, words[i])
            else:
                line += '%-*s' % (width, words[i])
            if i + nrows >= nwords:
                print_func(line)
                line = ''
            else:
                line += ' '


class CommandLineOutput(object):
    '''A class which allows easy integration of Cmd output into logging
    and also allows for easy capture of the output for testing purposes.

    '''

    def __init__(self, log=None):
        self.captured_output = None
        self.error_count = 0
        self.fatal_count = 0
        self.buffered_output = ''
        self.log = log or logging.getLogger(__name__)

    def set_capture_output(self, capture_output):
        '''Sets capture_output flag, which determines whether the logging
        output is captured or not.

        '''
        if capture_output:
            self.captured_output = []
        else:
            self.captured_output = None

    def get_captured_output(self):
        '''Returns the logging output which has been captured so far.'''
        return self.captured_output

    def get_error_count(self):
        '''Returns the number of errors which have been recorded in the
        currently captured output.

        '''
        return self.error_count

    def get_fatal_count(self):
        '''Returns the number of fatal errors which have been recorded in the
        currently captured output.

        '''
        return self.fatal_count

    def flush(self):
        '''Used by Cmd just after printing the prompt.'''
        prompt = self.buffered_output
        self.buffered_output = ''
        self.write_prompt(prompt)

    def debug(self, msg, *args, **kwargs):
        '''Captures and logs a debug level message.'''
        self.log.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        '''Captures and logs an info level message.'''
        if self.captured_output is not None:
            self.captured_output.append(('info', msg % args))
        self.log.info(msg, *args, **kwargs)

    def good(self, msg, *args, **kwargs):
        '''Logs a GOOD level string, which the color formatter prints as
        a green color..

        '''
        self.log.log(GOOD, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        '''Captures and logs an error level message.'''
        if self.captured_output is not None:
            self.captured_output.append(('error', msg % args))
        self.error_count += 1
        self.log.error(msg, *args, **kwargs)

    def fatal(self, msg, *args, **kwargs):
        '''Captures and logs an fatal level message.'''
        if self.captured_output is not None:
            self.captured_output.append(('fatal', msg % args))
        self.fatal_count += 1
        self.log.fatal(msg, *args, **kwargs)

    def write(self, string):
        '''Characters to output. Lines will be delimited by newline
        characters.

        This routine breaks the output into lines and logs each line
        individually.

        '''
        if len(self.buffered_output) > 0:
            string = self.buffered_output + string
            self.buffered_output = ''
        while True:
            nl_index = string.find('\n')
            if nl_index < 0:
                self.buffered_output = string
                return
            self.info(string[0:nl_index])
            string = string[nl_index + 1:]

    def write_prompt(self, prompt):
        '''A derived class can override this method to split out the
        prompt from regular output.

        '''
        sys.stdout.write(prompt)
        sys.stdout.flush()
        self.captured_output = []
        self.error_count = 0
        self.fatal_count = 0


class CommandLineBase(Cmd):
    '''Contains common customizations to the Cmd class.'''

    cmd_stack = []
    quitting = False
    output = None

    def __init__(self, log=None, filename=None, *args, **kwargs):
        if 'stdin' in kwargs:
            Cmd.use_rawinput = 0
        if not CommandLineBase.output:
            CommandLineBase.output = CommandLineOutput(log=log)
        self.log = CommandLineBase.output
        Cmd.__init__(self, stdout=self.log, *args, **kwargs)
        if '-' not in Cmd.identchars:
            Cmd.identchars += '-'
        self.filename = filename
        self.line_num = 0
        self.command = None
        self.columns = shutil.get_terminal_size().columns

        if len(CommandLineBase.cmd_stack) == 0:
            self.cmd_prompt = 'cli'
        else:
            self.cmd_prompt = CommandLineBase.cmd_stack[-1].command
        self.cmdloop_executed = False
        try:
            import readline
            delims = readline.get_completer_delims()
            readline.set_completer_delims(delims.replace('-', ''))
        except ImportError:
            pass

    def add_completion_funcs(self, names, complete_func_name):
        '''Helper function which adds a completion function for an array of
        command names.

        '''
        for name in names:
            name = name.replace('-', '_')
            func_name = 'complete_' + name
            cls = self.__class__
            try:
                getattr(cls, func_name)
            except AttributeError:
                setattr(cls, func_name, getattr(cls, complete_func_name))

    def default(self, line):
        '''Called when a command isn't recognized.'''
        raise ValueError('Unrecognized command: \'%s\'' % line)

    def emptyline(self):
        '''We want empty lines to do nothing. By default they would repeat the
        previous command.

        '''
        pass

    def update_prompt(self):
        '''Sets the prompt based on the current command stack.'''
        if Cmd.use_rawinput:
            prompts = [cmd.cmd_prompt for cmd in CommandLineBase.cmd_stack]
            self.prompt = ' '.join(prompts) + '> '
        else:
            self.prompt = ''

    def preloop(self):
        '''Update the prompt before cmdloop, which is where the prompt
        is used.

        '''
        Cmd.preloop(self)
        self.update_prompt()

    def postcmd(self, stop, line):
        '''We also update the prompt here since the command stack may
        have been modified.

        '''
        stop = Cmd.postcmd(self, stop, line)
        self.update_prompt()
        return stop

    def auto_cmdloop(self, line):
        '''If line is empty, then we assume that the user wants to enter
        commands, so we call cmdloop. If line is non-empty, then we assume
        that a command was entered on the command line, and we'll just
        execute it, and not hang around for user input. Things get
        interesting since we also used nested cmd loops. So if the user
        passes in 'servo 15' we'll process the servo 15 using onecmd, and
        then enter a cmdloop to process the servo specific command. The
        logic in this function basically says that if we ever waited for
        user input (i.e. called cmdloop) then we should continue to call
        cmdloop until the user decides to quit. That way if you run
        'bioloid.py servo 15' and then press Control-D you'll get to the
        servo prompt rather than exiting the program.

        '''
        CommandLineBase.cmd_stack.append(self)
        stop = self.auto_cmdloop_internal(line)
        CommandLineBase.cmd_stack.pop()
        return stop

    def auto_cmdloop_internal(self, line):
        '''The main code for auto_cmdloop.'''
        try:
            if len(line) == 0:
                self.cmdloop()
            else:
                self.onecmd(line)
                if (self.cmdloop_executed and
                        not CommandLineBase.quitting):
                    self.cmdloop()
        except KeyboardInterrupt:
            print('')
            CommandLineBase.quitting = True
            return True
        if CommandLineBase.quitting:
            return True

    def handle_exception(self, err, log=None):
        '''Common code for handling an exception.'''
        if not log:
            log = self.log.error
        base = CommandLineBase.cmd_stack[0]
        if base.filename is not None:
            log('File: %s Line: %d Error: %s',
                base.filename, base.line_num, err)
            CommandLineBase.quitting = True
            return True
        log('Error: %s', err)

    def onecmd(self, line):
        '''Override onecmd.

        1 - So we don't have to have a do_EOF method.
        2 - So we can strip comments
        3 - So we can track line numbers

        '''
        self.line_num += 1
        if line == 'EOF':
            if Cmd.use_rawinput:
                # This means that we printed a prompt, and we'll want to
                # print a newline to pretty things up for the caller.
                print('')
            return True
        # Strip comments
        comment_idx = line.find('#')
        if comment_idx >= 0:
            line = line[0:comment_idx]
            line = line.strip()
        try:
            return Cmd.onecmd(self, line)
        except ValueError as err:
            return self.handle_exception(err)

    def cmdloop(self, *args, **kwargs):
        '''We override this to support auto_cmdloop.'''
        self.cmdloop_executed = True
        return Cmd.cmdloop(self, *args, **kwargs)

    def parseline(self, line):
        '''Record the command that was executed. This also allows us to
         transform dashes back to underscores.

        '''
        (command, arg, line) = Cmd.parseline(self, line)
        self.command = command
        if command:
            command = command.replace('-', '_')
        return command, arg, line

    def completenames(self, text, *ignored):
        '''Override completenames so we can support names which have a dash
        in them.

        '''
        real_names = Cmd.completenames(self, text.replace('-', '_'), *ignored)
        return [string.replace('_', '-') for string in real_names]

    def do_help(self, arg):
        '''List available commands with 'help' or detailed help with
        'help cmd'.

        '''
        if not arg:
            return Cmd.do_help(self, arg)
        arg = arg.replace('-', '_')
        try:
            doc = getattr(self, 'do_' + arg).__doc__
            if doc:
                doc = doc.format(command=arg)
                self.stdout.write('%s\n' % trim(str(doc)))
                return
        except AttributeError:
            pass
        self.stdout.write('%s\n' % str(self.nohelp % (arg,)))
        return

    def print_topics(self, header, cmds, cmdlen, maxcol):
        '''Transform underscores to dashes when we print the command names.'''
        if isinstance(cmds, list):
            for i in range(len(cmds)):
                cmds[i] = cmds[i].replace('_', '-')
        Cmd.print_topics(self, header, cmds, cmdlen, maxcol)

    def do_quit(self, _):
        '''Exits from the program.'''
        CommandLineBase.quitting = True
        return True

    def print(self, s):
        self.log.info('%s', s)


class CommandLine(CommandLineBase):
    '''Implements the global level commands.
    '''

    def __init__(self, config, capture_output=False, *args, **kwargs):
        CommandLineBase.__init__(self, *args, **kwargs)
        self.log.set_capture_output(capture_output)
        self.config = config

    def gateway_names(self):
        return self.config.get('gateways').keys()

    def set_gateway(self, gateway_name):
        self.config.set_root('gateways', gateway_name)

    def complete_gateway(self, text, line, begin_idx, end_idx):
        '''Completion support for gateway command.'''
        return [gw_name for gw_name in self.gateway_names()
                if gw_name.startswith(text)]

    def do_gateway(self, line):
        '''cli> gateway gateway-name

        Connect to the indicated gateway.
        '''
        args = line.split()
        if len(args) != 1:
            raise ValueError("Expecting 1 argument1, found %d" % len(args))
        gateway_name = args[0]
        self.set_gateway(gateway_name)
        gateway = Gateway(gateway_name, self.config, log=self.log)
        return GatewayCommandLine(gateway).auto_cmdloop('')

    def do_gateways(self, _):
        '''cli> gateways

        List configured gateways.

        '''
        for gateway_name in self.gateway_names():
            self.log.info(gateway_name)

    def do_args(self, line):
        '''Prints out the command line arguments.'''
        self.log.info('args line = \'%s\'', line)

    def do_echo(self, line):
        '''Prints the rest of the line to the output.

        This is mostly useful when processing from a script.
        '''
        self.log.info('%s', line)


class GatewayCommandLine(CommandLineBase):

    def __init__(self, gateway, *args, **kwargs):
        CommandLineBase.__init__(self, *args, **kwargs)
        self.gateway = gateway
        self.cmd_prompt = gateway.url()

    def devices(self):
        devices = self.gateway.devices()
        if devices is None:
            self.log.error('Are you running with debug enabled? (i.e. npm start -- -d)')
            return []
        return devices

    def complete_device(self, text, line, begin_idx, end_idx):
        devices = self.devices()
        return [name for name in devices if name.startswith(text)]

    def do_device(self, line):
        '''cli gateway-name> device device-id

        Sets the current device.
        '''
        args = line.split()
        if len(args) != 1:
            raise ValueError("Expecting 1 argument, found %d" % len(args))
        id = args[0]
        device = self.gateway.device(id)
        if device:
            cmd_line = GatewayDeviceCommandLine(self.gateway, device)
            return cmd_line.auto_cmdloop('')
        self.log.error('No device found with the id "%s"', id)

    def do_devices(self, _):
        '''cli gateway-name> devices

        Prints a list of devices that the gateway knows about.
        '''
        devices = self.gateway.devices()
        if len(devices) > 0:
            print_cols(sorted(devices), self.print, self.columns)

    def complete_thing(self, text, line, begin_idx, end_idx):
        things = self.gateway.things()
        return [name for name in things if name.startswith(text)]

    def do_thing(self, line):
        '''cli gateway-name> thing thing-id

        Sets the current thing.
        '''
        args = line.split()
        if len(args) != 1:
            raise ValueError("Expecting 1 argument, found %d" % len(args))
        id = args[0]
        thing = self.gateway.thing(id)
        if thing:
            cmd_line = GatewayThingCommandLine(self.gateway, thing)
            return cmd_line.auto_cmdloop('')
        self.log.error('No thing found with the id "%s"', id)

    def do_things(self, line):
        '''cli gateway-name> things

        Prints a list of things that the gateway knows about.
        '''
        args = line.split()
        info = len(args) > 0 and args[0] == '-l'
        things = self.gateway.things(info)
        if len(things) > 0:
            if info:
              self.log.info(json.dumps(things, indent=2))
            else:
              print_cols(sorted(things), self.print, self.columns)


class GatewayDeviceCommandLine(CommandLineBase):

    def __init__(self, gateway, device, *args, **kwargs):
        CommandLineBase.__init__(self, *args, **kwargs)
        self.gateway = gateway
        self.device = device
        self.cmd_prompt = device['id']

    def do_adapter_devices(self, _):
      '''cli gateway-name> adapter-devices

      Sends a command to the adapter to report its devices.
      The information will show up on the gateway console.
      '''
      self.gateway.debugCmd(self.device['id'], 'devices', {})

    def do_adapter_info(self, line):
      '''cli gateway-name> adapter-info

      Sends a command to the adapter to report info on a device.
      The information will show up on the gateway console.
      '''
      params = {}
      args = line.split()
      if len(args) == 1:
        params['addr64'] = args[0]
      self.gateway.debugCmd(self.device['id'], 'info', params)

    def do_bind(self, line):
      '''cli gateway-name device-id> bind endpoint clusterId

      Binds an endpoint/cluster to the gateway. Note that this
      command just initiates the bind. You'll need to look at the
      gateway log to see the results.
      '''
      args = line.split()
      if len(args) != 2:
          raise ValueError('Expecting 2 arguments, found %d' % len(args))
      endpointNum = args[0]
      clusterId = args[1]
      clusterId = ('000' + clusterId)[-4:]
      self.gateway.bind(self.device['id'],
                        endpointNum,
                        clusterId)

    def do_bindings(self, _):
      '''cli gateway-name device-id> bindings

      Queries the current bindings from the current device. Note
      that this command just initiates the bindings table retrieval.
      You'll need to look at the gateway log to see the results.
      '''
      self.gateway.bindings(self.device['id']);

    def do_debug(self, line):
        '''cli gateway-name device-id> debug [[no]flow] [[no]frames] [[no]detail]

        Turns on frame dumping/debugging.
        '''
        args = line.split()
        params = {}
        for arg in args:
          if arg == 'flow':
            params['debugFlow'] = True
          elif arg == 'noflow':
            params['debugFlow'] = False
          elif arg == 'frames':
            params['debugFrames'] = True
          elif arg == 'noframes':
            params['debugFrames'] = False
          elif arg == 'detail':
            params['debugDumpFrameDetail'] = True
          elif arg == 'nodetail':
            params['debugDumpFrameDetail'] = False
          else:
            print('Unrecognized option:', arg, '(ignored)')
        self.gateway.debugCmd(self.device['id'], 'debug', params)

    def do_discover(self, line):
        '''cli gateway-name device-id> discover [endpointNum [clusterId]]

        Discovers attributes for the various clusters associated with
        a device.
        '''
        args = line.split()
        endpointNum = None
        clusterId = None
        if len(args) >= 1:
          endpointNum = args[0]
          if len(args) >= 2:
            clusterId = ('000' + args[1])[-4:]
        self.gateway.discoverAttr(self.device['id'], endpointNum, clusterId)

    def do_info(self, _):
        '''cli gateway-name device-id> info

        Prints information about the current device.
        '''
        id = self.device['id']
        self.device = self.gateway.device(id)
        self.log.info(json.dumps(self.device, indent=2))

    def do_read(self, line):
      '''cli gateway-name device-id> read endpoint clusterId attrId [attrId...]

      Reads one or more attributes from a zigbee device. Note that this
      command just initiates the read. You'll need to look at the gateway
      log to see the results.
      '''
      args = line.split()
      if len(args) < 3:
          raise ValueError('Expecting 2 or more arguments, found %d' % len(args))
      endpointNum = args[0]
      clusterId = args[1]
      attrIds = args[2:]
      clusterId = ('000' + clusterId)[-4:]

      if 'activeEndpoints' in self.device:
          if (endpointNum not in self.device['activeEndpoints']):
            raise ValueError('Unknown endpoint: %s' % endpointNum)
          endpoint = self.device['activeEndpoints'][endpointNum]
          self.gateway.readAttr(self.device['id'],
                                endpointNum,
                                260,
                                clusterId,
                                attrIds)
      else:
          self.log.error('No activeEndpoints found in device')


class GatewayThingCommandLine(CommandLineBase):

    def __init__(self, gateway, thing, *args, **kwargs):
        CommandLineBase.__init__(self, *args, **kwargs)
        self.gateway = gateway
        self.thing = thing
        self.cmd_prompt = os.path.basename(thing['href'])

    def id(self):
        return os.path.basename(self.thing['href'])

    def do_info(self, _):
        '''cli gateway-name thing-id> info

        Prints information about the current thing.
        '''
        self.thing = self.gateway.thing(self.id())
        self.log.info(json.dumps(self.thing, indent=2))

    def do_properties(self, _):
        '''cli gateway-name thing-id> properties

        Prints the properties associated with the current thing.
        '''
        properties = self.gateway.properties(self.id())
        self.log.info(json.dumps(properties, indent=2))

    def do_property(self, line):
        '''cli gateway-name thing-id> property property-name

        Prints information about the indicated property.
        '''
        args = line.split()
        for propertyName in args:
          property = self.gateway.property(self.id(), propertyName)
          self.log.info(json.dumps(property, indent=2))

