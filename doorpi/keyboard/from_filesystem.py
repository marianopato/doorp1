import doorpi
from doorpi.keyboard.AbstractBaseClass import KeyboardAbstractBaseClass, HIGH_LEVEL, LOW_LEVEL

import os
import ntpath
from time import sleep
from watchdog.observers import Observer
import watchdog.events

import logging
logger = logging.getLogger(__name__)
logger.debug('%s loaded', __name__)


def path_leaf(path):
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)


class MissingMandatoryParameter(Exception):
    pass


def get(**kwargs): return FileSystem(**kwargs)


class FileSystem(KeyboardAbstractBaseClass, FileSystemEventHandler):
    __reset_file = None

    def __init__(self, input_pins, output_pins, conf_pre, conf_post, keyboard_name, polarity=0, *args, **kwargs):
        logger.debug('FileSystem.__init__(input_pins = %s, output_pins = %s, polarity = %s)',
                     input_pins, output_pins, polarity)
        self.keyboard_name = keyboard_name
        self._polarity = polarity
        self._InputPins = list(map(str, input_pins))
        self._OutputPins = list(map(str, output_pins))

        section_name = conf_pre + 'keyboard' + conf_post
        self.__reset_input = doorpi.DoorPi().config.get_bool(
            section_name, 'reset_input', True)
        self.__base_path_input = doorpi.DoorPi().config.get_string_parsed(
            section_name, 'base_path_input')
        self.__base_path_output = doorpi.DoorPi().config.get_string_parsed(
            section_name, 'base_path_output')

        if not self.__base_path_input:
            raise MissingMandatoryParameter(
                ('base_path_input in {}').format(section_name))
        if not self.__base_path_output:
            raise MissingMandatoryParameter(
                ('base_path_output in {}}').format(section_name))

        os.makedirs(os.path.dirname(self.__base_path_input), exist_ok=True)
        os.makedirs(os.path.dirname(self.__base_path_output), exist_ok=True)

        for input_pin in self._InputPins:
            self.__set_input(os.path.join(self.__base_path_input, input_pin))
            self._register_EVENTS_for_pin(input_pin, __name__)

        self.__observer = Observer()
        self.__observer.schedule(self, self.__base_path_input)
        self.__observer.start()

        # use set_output to register status @ dict self.__OutputStatus
        for output_pin in self._OutputPins:
            self.set_output(output_pin, 0, False)

        self.register_destroy_action()

    def destroy(self):
        if self.is_destroyed:
            return

        # remove all doorpi events for this keyboard
        doorpi.DoorPi().event_handler.unregister_source(__name__, True)
        self.__destroyed = True

        self.__observer.stop()
        self.__observer.join()

        for input_pin in self._InputPins:
            try:
                os.remove(os.path.join(self.__base_path_input, input_pin))
            except FileNotFoundError:
                pass
            except Exception as ex:
                logger.error(
                    'Unable to remove virtual input pin %s: %s', input_pin, ex)
        for output_pin in self._OutputPins:
            try:
                os.remove(os.path.join(self.__base_path_output, output_pin))
            except FileNotFoundError:
                pass
            except Exception as ex:
                logger.error(
                    'Unable to remove virtual output pin %s: %s', output_pin, ex)

    def status_input(self, pin):
        if pin not in self._InputPins:
            return False
        with open(os.path.join(self.__base_path_input, pin), 'r') as file:
            plain_value = file.readline().rstrip()
            if self._polarity is 0:
                return str(plain_value).lower() in HIGH_LEVEL
            return str(plain_value).lower() in LOW_LEVEL

    def __write_file(self, file, value=False):
        with open(file, 'w') as f:
            value = str(value).lower() in HIGH_LEVEL
            if self._polarity is 1:
                value = not value
            f.write(str(value) + '\r\n')
        return value

    def __set_input(self, file, value=False):
        self.__write_file(file, value)
        os.chmod(file, 0o666)

    def set_output(self, pin, value, log_output=True):
        parsed_pin = doorpi.DoorPi().parse_string('!' + str(pin) + '!')
        if parsed_pin != ('!' + str(pin) + '!'):
            pin = parsed_pin

        if pin not in self._OutputPins:
            return False

        value = str(value).lower() in HIGH_LEVEL
        log_output = str(log_output).lower() in HIGH_LEVEL
        written_value = self.__write_file(
            os.path.join(self.__base_path_output, pin), value)
        if log_output:
            logger.debug('out(pin = %s, value = %s, log_output = %s)',
                         pin, written_value, log_output)

        self._OutputStatus[pin] = value
        return True

    def on_modified(self, event):
        if not isinstance(event, watchdog.events.FileModifiedEvent):
            return
        if self.__reset_file:
            if self.__reset_file == event.src_path:
                self.__reset_file = None
                logging.debug(
                    'reset inputfile will not fire event (%s)', event.src_path)
                return
            self.__reset_file = event.src_path
            self.__set_input(event.src_path, 'false')

        input_pin = path_leaf(event.src_path)
        if input_pin not in self._InputPins:
            return

        if self.status_input(input_pin):
            self.__reset_file = event.src_path
            self._fire_OnKeyPressed(input_pin, __name__)
            self._fire_OnKeyDown(input_pin, __name__)
        else:
            self._fire_OnKeyUp(input_pin, __name__)
