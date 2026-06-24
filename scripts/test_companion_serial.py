#!/usr/bin/env python3
import argparse
import struct
import sys
import time

try:
    import serial
except ImportError:
    print("Missing dependency: pyserial", file=sys.stderr)
    print("Install with: python -m pip install pyserial", file=sys.stderr)
    sys.exit(2)


CMD_APP_START = 1
CMD_SEND_TXT_MSG = 2
CMD_SYNC_NEXT_MESSAGE = 10
CMD_GET_BATT_AND_STORAGE = 20
CMD_DEVICE_QUERY = 22
CMD_SEND_TELEMETRY_REQ = 39
CMD_GET_CUSTOM_VARS = 40
CMD_GET_STATS = 56

RESP_CODE_SELF_INFO = 5
RESP_CODE_SENT = 6
RESP_CODE_CONTACT_MSG_RECV_V3 = 16
RESP_CODE_NO_MORE_MESSAGES = 10
RESP_CODE_BATT_AND_STORAGE = 12
RESP_CODE_DEVICE_INFO = 13
RESP_CODE_CUSTOM_VARS = 21
RESP_CODE_STATS = 24

PUSH_CODE_SEND_CONFIRMED = 0x82
PUSH_CODE_TELEMETRY_RESPONSE = 0x8B
PUSH_CODE_BINARY_RESPONSE = 0x8C

TXT_TYPE_CLI_DATA = 1

STATS_TYPE_CORE = 0
STATS_TYPE_RADIO = 1
STATS_TYPE_PACKETS = 2

MESHCOM_PREFIX = b"MESHCM"


def build_frame(payload: bytes) -> bytes:
    return b"<" + struct.pack("<H", len(payload)) + payload


def read_frame(ser: serial.Serial, timeout_s: float = 2.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        b = ser.read(1)
        if not b:
            continue
        if b != b">":
            continue
        hdr = ser.read(2)
        if len(hdr) != 2:
            return None
        length = struct.unpack("<H", hdr)[0]
        payload = ser.read(length)
        if len(payload) != length:
            return None
        return payload
    return None


def send_and_collect(ser: serial.Serial, name: str, payload: bytes, listen_s: float = 1.0):
    print(f"\n== {name} ==")
    print("TX:", payload.hex(" "))
    ser.write(build_frame(payload))
    ser.flush()
    frames = []
    deadline = time.time() + listen_s
    while time.time() < deadline:
        frame = read_frame(ser, timeout_s=min(0.35, max(0.05, deadline - time.time())))
        if frame is None:
            continue
        frames.append(frame)
    if not frames:
        print("RX: <timeout>")
        return []
    for idx, frame in enumerate(frames, start=1):
        print(f"RX[{idx}]:", frame.hex(" "))
        decode_frame(frame)
    return frames


def decode_frame(frame: bytes):
    code = frame[0]
    print(f"Code: 0x{code:02X} ({code})")
    if code == RESP_CODE_DEVICE_INFO:
        decode_device_info(frame)
    elif code == RESP_CODE_BATT_AND_STORAGE:
        decode_batt_and_storage(frame)
    elif code == RESP_CODE_SELF_INFO:
        print("Self info response received")
    elif code == RESP_CODE_CUSTOM_VARS:
        decode_custom_vars(frame)
    elif code == RESP_CODE_STATS:
        decode_stats(frame)
    elif code == RESP_CODE_CONTACT_MSG_RECV_V3:
        decode_contact_msg_recv_v3(frame)
    elif code == RESP_CODE_NO_MORE_MESSAGES:
        print("No more queued messages")
    elif code == RESP_CODE_SENT:
        decode_sent(frame)
    elif code == PUSH_CODE_SEND_CONFIRMED:
        decode_send_confirmed(frame)
    elif code == PUSH_CODE_TELEMETRY_RESPONSE:
        decode_telemetry(frame)
    elif code == PUSH_CODE_BINARY_RESPONSE:
        decode_binary_response(frame)
    else:
        print("Unhandled response")


def decode_c_string(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def decode_device_info(frame: bytes):
    if len(frame) < 80:
        print("Short DEVICE_INFO frame")
        return
    fw_ver_code = frame[1]
    max_contacts_x2 = frame[2]
    max_channels = frame[3]
    ble_pin = struct.unpack("<I", frame[4:8])[0]
    build_date = decode_c_string(frame[8:20])
    manufacturer = decode_c_string(frame[20:60])
    version = decode_c_string(frame[60:80]) if len(frame) >= 80 else ""
    print("Firmware code:", fw_ver_code)
    print("Max contacts:", max_contacts_x2 * 2)
    print("Max channels:", max_channels)
    print("BLE pin:", ble_pin)
    print("Build date:", build_date)
    print("Manufacturer:", manufacturer)
    if version:
        print("Version:", version)


def decode_batt_and_storage(frame: bytes):
    if len(frame) < 11:
        print("Short BATT_AND_STORAGE frame")
        return
    battery_mv = struct.unpack("<H", frame[1:3])[0]
    used_kb = struct.unpack("<I", frame[3:7])[0]
    total_kb = struct.unpack("<I", frame[7:11])[0]
    print("Battery:", f"{battery_mv} mV ({battery_mv / 1000.0:.2f} V)")
    print("Storage used:", f"{used_kb} KB")
    print("Storage total:", f"{total_kb} KB")


def decode_custom_vars(frame: bytes):
    raw = frame[1:].decode("utf-8", errors="replace")
    print("Custom vars:", raw if raw else "<empty>")


def decode_stats(frame: bytes):
    if len(frame) < 2:
        print("Short STATS frame")
        return
    stats_type = frame[1]
    if stats_type == STATS_TYPE_CORE and len(frame) >= 11:
        battery_mv = struct.unpack("<H", frame[2:4])[0]
        uptime_secs = struct.unpack("<I", frame[4:8])[0]
        err_flags = struct.unpack("<H", frame[8:10])[0]
        queue_len = frame[10]
        print("Stats type: core")
        print("Battery:", f"{battery_mv} mV ({battery_mv / 1000.0:.2f} V)")
        print("Uptime:", f"{uptime_secs} s")
        print("Error flags:", f"0x{err_flags:04X}")
        print("Outbound queue:", queue_len)
    elif stats_type == STATS_TYPE_RADIO and len(frame) >= 14:
        noise_floor = struct.unpack("<h", frame[2:4])[0]
        last_rssi = struct.unpack("<b", frame[4:5])[0]
        last_snr_q4 = struct.unpack("<b", frame[5:6])[0]
        tx_air_secs = struct.unpack("<I", frame[6:10])[0]
        rx_air_secs = struct.unpack("<I", frame[10:14])[0]
        print("Stats type: radio")
        print("Noise floor:", f"{noise_floor} dBm")
        print("Last RSSI:", f"{last_rssi} dBm")
        print("Last SNR:", f"{last_snr_q4 / 4.0:.2f} dB")
        print("TX airtime:", f"{tx_air_secs} s")
        print("RX airtime:", f"{rx_air_secs} s")
    elif stats_type == STATS_TYPE_PACKETS and len(frame) >= 30:
        values = struct.unpack("<IIIIIII", frame[2:30])
        labels = [
            "recv",
            "sent",
            "sent_flood",
            "sent_direct",
            "recv_flood",
            "recv_direct",
            "recv_errors",
        ]
        print("Stats type: packets")
        for label, value in zip(labels, values):
            print(f"{label}:", value)
    else:
        print(f"Unknown stats subtype {stats_type} or short frame")


def decode_sent(frame: bytes):
    if len(frame) < 10:
        print("Short SENT frame")
        return
    flood = frame[1]
    tag = struct.unpack("<I", frame[2:6])[0]
    est_timeout = struct.unpack("<I", frame[6:10])[0]
    print("Message accepted")
    print("Flood:", flood)
    print("Tag:", tag)
    print("Estimated timeout:", est_timeout)


def decode_send_confirmed(frame: bytes):
    if len(frame) < 9:
        print("Short SEND_CONFIRMED frame")
        return
    ack = struct.unpack("<I", frame[1:5])[0]
    trip_time = struct.unpack("<I", frame[5:9])[0]
    print("Send confirmed")
    print("Ack/tag:", ack)
    print("Trip time:", trip_time)


def decode_binary_response(frame: bytes):
    if len(frame) < 6:
        print("Short BINARY_RESPONSE frame")
        return
    reserved = frame[1]
    tag = struct.unpack("<I", frame[2:6])[0]
    text = frame[6:].decode("utf-8", errors="replace").rstrip("\x00")
    print("Binary response reserved:", reserved)
    print("Binary response tag:", tag)
    print("Binary response text:")
    print(text if text else "<empty>")


def decode_contact_msg_recv_v3(frame: bytes):
    if len(frame) < 16:
        print("Short CONTACT_MSG_RECV_V3 frame")
        return
    snr_q4 = struct.unpack("<b", frame[1:2])[0]
    reserved1 = frame[2]
    reserved2 = frame[3]
    pubkey_prefix = frame[4:10].hex()
    path_len = frame[10]
    txt_type = frame[11]
    timestamp = struct.unpack("<I", frame[12:16])[0]
    text = frame[16:].decode("utf-8", errors="replace").rstrip("\x00")
    print("Queued contact message")
    print("SNR:", f"{snr_q4 / 4.0:.2f} dB")
    print("Reserved:", reserved1, reserved2)
    print("From pubkey prefix:", pubkey_prefix)
    print("Path len:", path_len)
    print("Text type:", txt_type)
    print("Timestamp:", timestamp)
    print("Text:")
    print(text if text else "<empty>")


def _read_i16_be(buf: bytes) -> int:
    return struct.unpack(">h", buf)[0]


def _read_u16_be(buf: bytes) -> int:
    return struct.unpack(">H", buf)[0]


def _read_u32_be(buf: bytes) -> int:
    return struct.unpack(">I", buf)[0]


def _read_i24_be(buf: bytes) -> int:
    val = int.from_bytes(buf, "big", signed=False)
    if val & 0x800000:
        val -= 1 << 24
    return val


def parse_lpp(payload: bytes):
    i = 0
    items = []
    while i + 2 <= len(payload):
        channel = payload[i]
        data_type = payload[i + 1]
        i += 2
        if data_type in (0, 1, 102, 120, 142):
            if i + 1 > len(payload):
                break
            value = payload[i]
            i += 1
            items.append((channel, data_type, value))
        elif data_type in (2, 3):
            if i + 2 > len(payload):
                break
            value = _read_i16_be(payload[i:i + 2]) / 100.0
            i += 2
            items.append((channel, data_type, value))
        elif data_type in (101, 115, 125, 128, 132):
            if i + 2 > len(payload):
                break
            value = _read_u16_be(payload[i:i + 2])
            i += 2
            if data_type == 115:
                value /= 10.0
            items.append((channel, data_type, value))
        elif data_type == 121:
            if i + 2 > len(payload):
                break
            value = _read_i16_be(payload[i:i + 2])
            i += 2
            items.append((channel, data_type, value))
        elif data_type == 103:
            if i + 2 > len(payload):
                break
            value = _read_i16_be(payload[i:i + 2]) / 10.0
            i += 2
            items.append((channel, data_type, value))
        elif data_type == 104:
            if i + 1 > len(payload):
                break
            value = payload[i] / 2.0
            i += 1
            items.append((channel, data_type, value))
        elif data_type in (116,):
            if i + 2 > len(payload):
                break
            value = _read_u16_be(payload[i:i + 2]) / 100.0
            i += 2
            items.append((channel, data_type, value))
        elif data_type in (117,):
            if i + 2 > len(payload):
                break
            value = _read_u16_be(payload[i:i + 2]) / 1000.0
            i += 2
            items.append((channel, data_type, value))
        elif data_type in (100, 118, 131, 133):
            if i + 4 > len(payload):
                break
            value = _read_u32_be(payload[i:i + 4])
            i += 4
            if data_type == 131:
                value /= 1000.0
            items.append((channel, data_type, value))
        elif data_type == 130:
            if i + 4 > len(payload):
                break
            value = _read_u32_be(payload[i:i + 4]) / 1000.0
            i += 4
            items.append((channel, data_type, value))
        elif data_type in (113, 134):
            if i + 6 > len(payload):
                break
            x = _read_i16_be(payload[i:i + 2])
            y = _read_i16_be(payload[i + 2:i + 4])
            z = _read_i16_be(payload[i + 4:i + 6])
            i += 6
            scale = 1000.0 if data_type == 113 else 100.0
            items.append((channel, data_type, (x / scale, y / scale, z / scale)))
        elif data_type == 136:
            if i + 9 > len(payload):
                break
            lat = _read_i24_be(payload[i:i + 3]) / 10000.0
            lon = _read_i24_be(payload[i + 3:i + 6]) / 10000.0
            alt = _read_i24_be(payload[i + 6:i + 9]) / 100.0
            i += 9
            items.append((channel, data_type, (lat, lon, alt)))
        else:
            items.append((channel, data_type, "<unknown>"))
            break
    return items


def format_lpp_item(channel: int, data_type: int, value):
    names = {
        0: "digital_input",
        1: "digital_output",
        2: "analog_input",
        3: "analog_output",
        100: "generic_sensor",
        101: "luminosity",
        102: "presence",
        103: "temperature_c",
        104: "humidity_pct",
        113: "accelerometer_g",
        115: "barometric_hpa",
        116: "voltage_v",
        117: "current_a",
        118: "frequency_hz",
        120: "percentage",
        121: "altitude_m",
        125: "concentration_ppm",
        128: "power_w",
        130: "distance_m",
        131: "energy_kwh",
        132: "direction_deg",
        133: "unixtime",
        134: "gyrometer_dps",
        136: "gps",
        142: "switch",
    }
    return f"ch{channel} {names.get(data_type, f'type_{data_type}')} = {value}"


def drain_sync_messages(ser: serial.Serial, max_reads: int = 8):
    for idx in range(max_reads):
        frames = send_and_collect(
            ser,
            f"CMD_SYNC_NEXT_MESSAGE #{idx + 1}",
            bytes([CMD_SYNC_NEXT_MESSAGE]),
            listen_s=0.7,
        )
        if not frames:
            break
        if any(frame[:1] == bytes([RESP_CODE_NO_MORE_MESSAGES]) for frame in frames):
            break


def decode_telemetry(frame: bytes):
    if len(frame) < 8:
        print("Short TELEMETRY_RESPONSE frame")
        return
    reserved = frame[1]
    pubkey_prefix = frame[2:8].hex()
    lpp = frame[8:]
    print("Telemetry reserved:", reserved)
    print("Telemetry pubkey prefix:", pubkey_prefix)
    print("Telemetry raw LPP:", lpp.hex(" "))
    items = parse_lpp(lpp)
    if not items:
        print("Telemetry parsed: <empty>")
        return
    print("Telemetry parsed:")
    for channel, data_type, value in items:
        print(format_lpp_item(channel, data_type, value))


def build_meshcomod_cli(command: str) -> bytes:
    return (
        bytes([CMD_SEND_TXT_MSG, TXT_TYPE_CLI_DATA, 0])
        + struct.pack("<I", 0)
        + MESHCOM_PREFIX
        + command.encode("utf-8")
    )


def main():
    parser = argparse.ArgumentParser(description="Probe WADAMESH companion protocol over serial")
    parser.add_argument("--port", required=True, help="Serial port, e.g. COM4")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate")
    args = parser.parse_args()

    with serial.Serial(args.port, args.baud, timeout=0.25) as ser:
        time.sleep(0.2)
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass

        device_query = bytes([CMD_DEVICE_QUERY, 3])
        app_start = bytes([CMD_APP_START]) + bytes(7) + b"wadamesh-probe"

        send_and_collect(ser, "CMD_DEVICE_QUERY", device_query, listen_s=0.8)
        send_and_collect(ser, "CMD_APP_START", app_start, listen_s=0.8)
        drain_sync_messages(ser, max_reads=4)
        send_and_collect(ser, "CMD_GET_BATT_AND_STORAGE", bytes([CMD_GET_BATT_AND_STORAGE]), listen_s=0.8)
        send_and_collect(ser, "CMD_GET_CUSTOM_VARS", bytes([CMD_GET_CUSTOM_VARS]), listen_s=0.8)
        send_and_collect(ser, "CMD_GET_STATS core", bytes([CMD_GET_STATS, STATS_TYPE_CORE]), listen_s=0.8)
        send_and_collect(ser, "CMD_GET_STATS radio", bytes([CMD_GET_STATS, STATS_TYPE_RADIO]), listen_s=0.8)
        send_and_collect(ser, "CMD_GET_STATS packets", bytes([CMD_GET_STATS, STATS_TYPE_PACKETS]), listen_s=0.8)
        send_and_collect(ser, "CMD_SEND_TELEMETRY_REQ self", bytes([CMD_SEND_TELEMETRY_REQ, 0, 0, 0]), listen_s=1.2)
        send_and_collect(ser, "CMD_SEND_TXT_MSG meshcomod status", build_meshcomod_cli("status"), listen_s=1.5)
        drain_sync_messages(ser, max_reads=4)
        send_and_collect(ser, "CMD_SEND_TXT_MSG meshcomod wifi status", build_meshcomod_cli("wifi status"), listen_s=1.5)
        drain_sync_messages(ser, max_reads=4)
        send_and_collect(ser, "CMD_SEND_TXT_MSG meshcomod ota status", build_meshcomod_cli("ota status"), listen_s=1.5)
        drain_sync_messages(ser, max_reads=4)


if __name__ == "__main__":
    main()
