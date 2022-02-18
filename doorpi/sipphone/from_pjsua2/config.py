"""Configuration utilities for the PJSUA sipphone module"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

import pjsua2 as pj

import doorpi

if TYPE_CHECKING:
    from . import glue

LOGGER: doorpi.DoorPiLogger = logging.getLogger(__name__)  # type: ignore


def call_timeout() -> int:
    """Fetches the configured call timeout duration."""
    return doorpi.INSTANCE.config["sipphone.ringtime"]


def max_call_time() -> int:
    """Fetches the configured maximum call time."""
    return doorpi.INSTANCE.config["sipphone.calltime"]


def sipphone_server() -> str:
    """Fetches the SIP server from the configuration."""
    return doorpi.INSTANCE.config["sipphone.server.server"]


def account_config() -> pj.AccountConfig:
    """Creates the PJSUA2 AccountConfig object."""
    LOGGER.trace("Creating account config")
    acfg = pj.AccountConfig()
    identity = doorpi.INSTANCE.config["sipphone.server.identity"]
    sip_server = sipphone_server()
    sip_user = doorpi.INSTANCE.config["sipphone.server.username"]
    sip_pass = doorpi.INSTANCE.config["sipphone.server.password"]
    sip_realm = doorpi.INSTANCE.config["sipphone.server.realm"] or sip_server

    if identity:
        identity = identity.replace("\\", "\\\\").replace('"', '\\"')
        acfg.idUri = f'"{identity}" <sip:{sip_user}@{sip_server}>'
    else:
        acfg.idUri = f"sip:{sip_user}@{sip_server}"

    acfg.regConfig.registrarUri = f"sip:{sip_server}"
    acfg.regConfig.registerOnAdd = True

    authCred = pj.AuthCredInfo()
    authCred.scheme = "digest"
    authCred.realm = sip_realm
    authCred.username = sip_user
    authCred.dataType = 0  # plain text password
    authCred.data = sip_pass
    acfg.sipConfig.authCreds.append(authCred)

    acfg.presConfig.publishEnabled = True
    return acfg


def dialtone_config() -> dict:
    """Collects the dial tone related settings from the configuration."""
    try:
        filename = doorpi.INSTANCE.config["sipphone.dialtone.file"]
    except KeyError:
        filename = None

    return {
        "filename": filename,
        "loudness": doorpi.INSTANCE.config["sipphone.dialtone.loudness"],
    }


def endpoint_config() -> pj.EpConfig:
    """Creates the PJSUA2 Endpoint configuration object."""
    LOGGER.trace("Creating endpoint config")
    ep_cfg = pj.EpConfig()
    ep_cfg.uaConfig.maxCalls = doorpi.INSTANCE.config["sipphone.max_calls"]
    stun_server = doorpi.INSTANCE.config["sipphone.stunserver"]
    if stun_server:
        ep_cfg.uaConfig.stunServer.append(stun_server)
    # Ensure PJSIP callbacks will be handled by our python worker thread
    ep_cfg.uaConfig.threadCnt = 0
    ep_cfg.uaConfig.mainThreadOnly = True

    ep_cfg.logConfig.msgLogging = False  # Don't log full SIP messages
    ep_cfg.logConfig.level = 5
    ep_cfg.logConfig.consoleLevel = 4
    ep_cfg.logConfig.decor = False

    native_logger = ".".join(__name__.split(".")[:-1] + ["native"])
    logwriter = DoorPiLogWriter(
        cast(doorpi.DoorPiLogger, logging.getLogger(native_logger))
    )
    ep_cfg.logConfig.writer = logwriter
    # Bind the LogWriter's lifetime to the sipphone object, so that
    # it won't be garbage-collected prematurely.
    sp: glue.Pjsua2 = doorpi.INSTANCE.sipphone  # type: ignore
    sp._logwriter = logwriter  # pylint: disable=protected-access

    return ep_cfg


def recorder_config() -> dict:
    """Collects the call recorder settings from the configuration."""
    return {
        "path": (
            doorpi.INSTANCE.config["sipphone.recording.path"]
            if doorpi.INSTANCE.config["sipphone.recording.enabled"]
            else None
        ),
        "early": doorpi.INSTANCE.config["sipphone.recording.dial"],
        "keep": doorpi.INSTANCE.config["sipphone.recording.keep"],
    }


def transport_config() -> pj.TransportConfig:
    """Creates the PJSUA2 TransportConfig object."""
    LOGGER.trace("Creating transport config")
    t_cfg = pj.TransportConfig()
    t_cfg.port = doorpi.INSTANCE.config["sipphone.server.localport"]
    return t_cfg


def list_audio_devices(adm: pj.AudDevManager, loglevel: int) -> None:
    """Logs the audio devices known to ``adm`` with the given ``loglevel``."""
    if not LOGGER.isEnabledFor(loglevel):
        return
    devs = adm.enumDev2()
    for dev in devs:
        LOGGER.log(loglevel, "   %s:%s", dev.driver, dev.name)


def setup_audio(endpoint: pj.Endpoint) -> None:
    """Sets up everything audio on the given endpoint."""
    LOGGER.trace("Setting up audio on %s", repr(endpoint))
    adm = endpoint.audDevManager()
    setup_audio_devices(adm)
    setup_audio_volume(adm)
    setup_audio_codecs(endpoint)
    setup_audio_echo_cancellation(adm)


def setup_audio_devices(adm: pj.AudDevManager) -> None:
    """Sets up PJSUA so that it uses the configured audio devices."""
    LOGGER.trace("PJSUA2 found %d audio devices", adm.getDevCount())
    if adm.getDevCount() == 0:
        raise RuntimeError("No audio devices found by PJSUA2")

    # Setup configured capture / playback devices
    capture_device = doorpi.INSTANCE.config["sipphone.capture.device"]
    playback_device = doorpi.INSTANCE.config["sipphone.playback.device"]
    if capture_device == "" or playback_device == "":
        LOGGER.critical("No audio devices configured! Detected audio devices:")
        list_audio_devices(adm, logging.CRITICAL)
        raise ValueError(
            "No audio devices configured (See log for possible options)"
        )

    capture_drv = capture_device.split(":")[0]
    # The split-rejoin is necessary to handle device names with ":"
    capture_dev = ":".join(capture_device.split(":")[1:])
    playback_drv = playback_device.split(":")[0]
    playback_dev = ":".join(playback_device.split(":")[1:])
    try:
        capture_idx = adm.lookupDev(capture_drv, capture_dev)
    except pj.Error:
        LOGGER.critical("Configured capture device not found! Found devices:")
        list_audio_devices(adm, logging.CRITICAL)
        raise ValueError(
            f"Configured capture device could not be found: {capture_device}"
        ) from None
    try:
        playback_idx = adm.lookupDev(playback_drv, playback_dev)
    except pj.Error:
        LOGGER.critical("Configured playback device not found! Found devices:")
        list_audio_devices(adm, logging.CRITICAL)
        raise ValueError(
            f"Configured playback device could not be found: {playback_device}"
        ) from None
    LOGGER.trace(
        "Device indices: capture = %d, playback = %d",
        capture_idx,
        playback_idx,
    )
    adm.setCaptureDev(capture_idx)
    adm.setPlaybackDev(playback_idx)


def setup_audio_volume(adm: pj.AudDevManager) -> None:
    """Configures the volume settings on the used audio devices."""
    capture_volume = doorpi.INSTANCE.config["sipphone.capture.volume"]
    playback_volume = doorpi.INSTANCE.config["sipphone.playback.volume"]
    if playback_volume >= 0:
        LOGGER.trace("Setting playback volume to %d", playback_volume)
        try:
            adm.setOutputVolume(playback_volume, True)
        except pj.Error as err:
            LOGGER.error(
                "Unable to set playback volume "
                "(Set sipphone.playback.volume to -1 to silence this)\n%s",
                err.info(),
            )
    if capture_volume >= 0:
        LOGGER.trace("Setting capture volume to %d", playback_volume)
        try:
            adm.setInputVolume(capture_volume, True)
        except pj.Error as err:
            LOGGER.error(
                "Unable to set capture volume "
                "(Set sipphone.capture.volume to -1 to silence this)\n%s",
                err.info(),
            )


def setup_audio_codecs(endpoint: pj.Endpoint) -> None:
    """Configures the enabled codecs in PJSUA2."""
    allcodecs = endpoint.codecEnum2()
    LOGGER.debug(
        "Supported audio codecs: %s", ", ".join(c.codecId for c in allcodecs)
    )
    confcodecs = doorpi.INSTANCE.config["sipphone.codecs"]
    if not confcodecs:
        return

    confcodecs = [c.strip().lower() for c in confcodecs]
    for codec in allcodecs:
        # In PJSIP, codecs follow the format "codec/samplerate/num".
        # Since the same codec can exist multiple times with
        # different sample rate, we need to check each part of the
        # codec ID individually.
        ci = codec.codecId.lower()
        cn, cs, _ = ci.split("/")
        new_priority = 0
        for match in [ci, "/".join([cn, cs]), cn]:
            i = None
            try:
                i = confcodecs.index(match)
            except ValueError:
                continue
            new_priority = 255 - i  # 255 = highest priority
            break
        LOGGER.trace(
            "Changing priority of codec %s from %d to %d",
            codec.codecId,
            codec.priority,
            new_priority,
        )
        endpoint.codecSetPriority(codec.codecId, new_priority)


def setup_audio_echo_cancellation(adm: pj.AudDevManager) -> None:
    """Sets up echo cancellation in PJSUA2."""
    if doorpi.INSTANCE.config["sipphone.echo_cancellation.enabled"]:
        tail = doorpi.INSTANCE.config["sipphone.echo_cancellation.tail"]
        LOGGER.trace("Setting echo cancellation tail length to %dms", tail)
        adm.setEcOptions(tail, 0)
    else:
        LOGGER.trace("Disabling echo cancellation")
        adm.setEcOptions(0, 0)


# pylint: disable=too-few-public-methods
class DoorPiLogWriter(pj.LogWriter):
    """Redirects output from the PJSUA2 native module to a Python logger"""

    def __init__(self, logger: doorpi.DoorPiLogger) -> None:
        super().__init__()
        self.__logger = logger

    def write(self, entry: pj.LogEntry) -> None:
        if entry.level <= 1:
            self.__logger.error("%s", entry.msg)
        elif entry.level <= 2:
            self.__logger.warning("%s", entry.msg)
        elif entry.level <= 3:
            self.__logger.info("%s", entry.msg)
        elif entry.level <= 4:
            self.__logger.debug("%s", entry.msg)
        else:
            self.__logger.trace("[level %d] %s", entry.level, entry.msg)
