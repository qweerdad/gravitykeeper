"""Minimal offline Protobuf wire inspection for Antigravity step rows."""

from collections import defaultdict


def read_integer(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("incomplete protobuf integer")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError("oversized protobuf integer")


def fields(data):
    values = defaultdict(list)
    offset = 0
    while offset < len(data):
        tag, offset = read_integer(data, offset)
        number, wire_type = tag >> 3, tag & 7
        if not number:
            raise ValueError("invalid protobuf field")
        if wire_type == 0:
            value, offset = read_integer(data, offset)
        else:
            if wire_type == 2:
                length, offset = read_integer(data, offset)
            elif wire_type in (1, 5):
                length = 8 if wire_type == 1 else 4
            else:
                raise ValueError(f"unexpected protobuf wire type {wire_type}")
            if offset + length > len(data):
                raise ValueError("invalid protobuf field length")
            value = data[offset:offset + length]
            offset += length
        values[number].append(value)
    return dict(values)


def descend(data, *field_numbers):
    value = data
    for number in field_numbers:
        candidates = fields(value).get(number, [])
        if len(candidates) != 1:
            raise ValueError(f"expected one occurrence of protobuf field {number}")
        value = candidates[0]
    return value
