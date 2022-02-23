# -*- coding: utf-8 -*-
import doorpi
from doorpi.action.base import SingleAction

import subprocess as sub
import os
import datetime
import glob

import logging
logger = logging.getLogger(__name__)
logger.debug('%s loaded', __name__)

conf = doorpi.DoorPi().config
DOORPI_SECTION = 'DoorPi'


def get_last_snapshot(snapshot_path=None):
    if not snapshot_path:
        snapshot_path = conf.get_string_parsed(DOORPI_SECTION, 'snapshot_path', '/tmp')
    files = sorted(glob.glob(os.path.join(snapshot_path, '*.*')), key=os.path.getctime)
    if len(files) == 0:
        return False
    return files[-1]


def get_next_filename(snapshot_path):
    if not os.path.exists(snapshot_path):
        os.makedirs(snapshot_path)

    files = sorted(glob.glob(os.path.join(snapshot_path, '*.*')), key=os.path.getctime)
    if len(files) > conf.get_int(DOORPI_SECTION, 'number_of_snapshots', 10):
        try:
            os.remove(os.path.join(snapshot_path, files[0]))
        except OSError as exp:
            logger.warning(('delete snapshot file {0} failed with error {1}').format(files[0], exp))

    return os.path.join(snapshot_path,
                        datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + '.jpg')


def get_snapshot_from_picam(snapshot_path):
    import picamera
    filename = get_next_filename(snapshot_path)
    with picamera.PiCamera() as camera:
        camera.resolution = (1024, 768)
        camera.capture(filename)
    conf.set_value(DOORPI_SECTION, 'last_snapshot', filename)
    return filename


def get_snapshot_from_url(snapshot_path, url):
    import requests
    filename = get_next_filename(snapshot_path)
    r = requests.get(url, stream=True)
    with open(filename, 'wb') as fd:
        for chunk in r.iter_content(1024):
            fd.write(chunk)
    conf.set_value(DOORPI_SECTION, 'last_snapshot', filename)
    return filename


def get_snapshot_from_stream(snapshot_path, url):
    import cv2
    filename = get_next_filename(snapshot_path)
    cap = cv2.VideoCapture(url)
    if cap.isOpened():
        ret, frame = cap.read()
        if ret:
            cv2.imwrite(filename, frame)

    cap.release()
    conf.set_value(DOORPI_SECTION, 'last_snapshot', filename)
    return filename


def get(parameters=''):
    snapshot_path = conf.get_string_parsed(DOORPI_SECTION, 'snapshot_path', '/tmp')
    if parameters == '': 
        return SnapShotAction(get_snapshot_from_picam, snapshot_path=snapshot_path)
 
    parameter_list = parameters.split(',')
    if len(parameter_list) is not 2:
        return None

    type = parameter_list[0]
    url = parameter_list[1]

    if type.upper() == 'STREAM':
        return SnapShotAction(get_snapshot_from_stream, snapshot_path=snapshot_path, url=url)
    return SnapShotAction(get_snapshot_from_url, snapshot_path=snapshot_path, url=url)


class SnapShotAction(SingleAction):
    pass
