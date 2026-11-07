import secrets

from bumble import data_types, hci
from bumble.controller import Controller
from bumble.core import AdvertisingData
from bumble.hci import CodecID, CodingFormat
from bumble.pairing import PairingConfig
from bumble.profiles.ascs import AudioStreamControlService
from bumble.profiles.bap import (
    AudioLocation,
    CodecSpecificCapabilities,
    ContextType,
    SupportedFrameDuration,
    SupportedSamplingFrequency,
    UnicastServerAdvertisingData,
)
from bumble.profiles.cap import CommonAudioServiceService
from bumble.profiles.csip import CoordinatedSetIdentificationService, SirkType
from bumble.profiles.pacs import PacRecord, PublishedAudioCapabilitiesService

from pytest_bluezenv import (
    Bluetoothctl,
    Bluetoothd,
    BumbleController,
    BumbleDevice,
    host_config,
)

BAP_CONF = """[General]
Experimental = true
KernelExperimental = true
ControllerMode = le
"""

ISO_COMMANDS = {
    hci.HCI_LE_SET_CIG_PARAMETERS_COMMAND,
    hci.HCI_LE_CREATE_CIS_COMMAND,
    hci.HCI_LE_REMOVE_CIG_COMMAND,
    hci.HCI_LE_ACCEPT_CIS_REQUEST_COMMAND,
    hci.HCI_LE_REJECT_CIS_REQUEST_COMMAND,
    hci.HCI_LE_SETUP_ISO_DATA_PATH_COMMAND,
    hci.HCI_LE_REMOVE_ISO_DATA_PATH_COMMAND,
}

ISO_FEATURES = (
    hci.LeFeatureMask.CONNECTED_ISOCHRONOUS_STREAM_CENTRAL
    | hci.LeFeatureMask.CONNECTED_ISOCHRONOUS_STREAM_PERIPHERAL
)


def enable_iso(controller):
    # Disable LL privacy: the emulated link cannot follow BlueZ changing
    # its LE random address.
    controller.le_features = (
        controller.le_features | ISO_FEATURES
    ) & ~hci.LeFeatureMask.LL_PRIVACY
    controller.supported_commands |= ISO_COMMANDS


class IsoController(Controller):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        enable_iso(self)

    def on_hci_le_set_random_address_command(self, command):
        self.random_address = self.public_address
        return hci.HCI_StatusReturnParameters(hci.HCI_ErrorCode.SUCCESS)


def sink_pac_record():
    return PacRecord(
        coding_format=CodingFormat(CodecID.LC3),
        codec_specific_capabilities=CodecSpecificCapabilities(
            supported_sampling_frequencies=(
                SupportedSamplingFrequency.FREQ_8000
                | SupportedSamplingFrequency.FREQ_16000
                | SupportedSamplingFrequency.FREQ_24000
                | SupportedSamplingFrequency.FREQ_32000
                | SupportedSamplingFrequency.FREQ_48000
            ),
            supported_frame_durations=(
                SupportedFrameDuration.DURATION_7500_US_SUPPORTED
                | SupportedFrameDuration.DURATION_10000_US_SUPPORTED
            ),
            supported_audio_channel_count=[1, 2],
            min_octets_per_codec_frame=26,
            max_octets_per_codec_frame=240,
            supported_max_codec_frames_per_sdu=2,
        ),
    )


def add_unicast_server(device):
    device.cis_enabled = True
    device.pairing_config_factory = lambda connection: PairingConfig(mitm=False)
    enable_iso(device.host.controller.sink)

    csis = CoordinatedSetIdentificationService(
        set_identity_resolving_key=secrets.token_bytes(16),
        set_identity_resolving_key_type=SirkType.PLAINTEXT,
    )
    # Add CSIS first: bumble would otherwise nest its service definition
    # inside CAP, which is invalid per the GATT specification.
    device.add_service(csis)
    device.add_service(CommonAudioServiceService(csis))
    device.add_service(
        PublishedAudioCapabilitiesService(
            supported_source_context=ContextType.PROHIBITED,
            available_source_context=ContextType.PROHIBITED,
            supported_sink_context=ContextType(0xFF),
            available_sink_context=ContextType(0xFF),
            sink_audio_locations=(AudioLocation.FRONT_LEFT | AudioLocation.FRONT_RIGHT),
            sink_pac=[sink_pac_record()],
        )
    )
    device.add_service(
        AudioStreamControlService(device, sink_ase_id=[1], source_ase_id=[2])
    )

    device.advertising_data = (
        bytes(
            AdvertisingData(
                [
                    data_types.CompleteLocalName("Bumble LE Audio"),
                    data_types.IncompleteListOf16BitServiceUUIDs(
                        [PublishedAudioCapabilitiesService.UUID]
                    ),
                ]
            )
        )
        + csis.get_advertising_data()
        + bytes(UnicastServerAdvertisingData())
    )


@host_config(
    [Bluetoothd(conf=BAP_CONF), Bluetoothctl(args=("-a", "auto:NoInputNoOutput"))],
    controller=BumbleController(
        controllers=IsoController,
        devices={
            "server": BumbleDevice(
                config={"name": "Bumble LE Audio"},
                setup=add_unicast_server,
            )
        },
    ),
)
def test_unicast_server(hosts, bumble_env):
    (host0,) = hosts
    server = bumble_env.devices["server"]
    address = server.static_address.to_string(False)

    host0.bluetoothctl.send("power on\n")
    host0.bluetoothctl.expect("Changing power on succeeded")
    host0.bluetoothctl.send(
        "endpoint.register 00002bcb-0000-1000-8000-00805f9b34fb 0x06\n"
        "y\na\n3\n0x000f\n0x000f\na\na\n"
    )
    host0.bluetoothctl.expect("Endpoint /local/endpoint/ep0 registered")

    host0.bluetoothctl.send("scan on\n")
    host0.bluetoothctl.expect(f"Device {address} Bumble LE Audio")
    host0.bluetoothctl.send(f"pair {address}\n")
    host0.bluetoothctl.expect("Pairing successful")

    dev = address.replace(":", "_")
    host0.bluetoothctl.expect(f"Transport /org/bluez/hci0/dev_{dev}")
