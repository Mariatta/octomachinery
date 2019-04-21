"""Utility helpers for CLI."""

import itertools
import json

import multidict
import yaml


def _probe_yaml(event_file_fd):
    try:
        http_headers, event, extra = itertools.islice(
            itertools.chain(
                yaml.safe_load_all(event_file_fd),
                (None, ) * 3,
            ),
            3,
        )
    except yaml.parser.ParserError:
        raise ValueError('YAML file is not valid')
    finally:
        event_file_fd.seek(0)

    if extra is not None:
        raise ValueError('YAML file must only contain 1–2 documents')

    if event is None:
        event = http_headers
        http_headers = ()

    if event is None:
        raise ValueError('YAML file must contain 1–2 non-empty documents')

    return http_headers, event


def _probe_jsonl(event_file_fd):
    first_line = event_file_fd.readline()
    second_line = event_file_fd.readline()
    third_line = event_file_fd.readline()
    event_file_fd.seek(0)

    if third_line:
        raise ValueError('JSONL file must only contain 1–2 JSON lines')

    http_headers = json.loads(first_line)

    try:
        event = json.loads(second_line)
    except ValueError:
        event = None

    if event is None:
        event = http_headers
        http_headers = ()

    return http_headers, event


def _probe_json(event_file_fd):
    event = json.load(event_file_fd)
    event_file_fd.seek(0)

    if not isinstance(event, dict):
        raise ValueError('JSON file must only contain an object mapping')

    http_headers = ()

    return http_headers, event


def _parse_fd_content(event_file_fd):
    """Guess file content type and read event with HTTP headers."""
    for event_reader in _probe_yaml, _probe_jsonl:
        try:
            return event_reader(event_file_fd)
        except ValueError:
            pass

    # Last probe call is outside the loop to propagate exception further
    return _probe_json(event_file_fd)


def _transform_http_headers_list_to_multidict(headers):
    return multidict.CIMultiDict(next(iter(h.items()), ()) for h in headers)


def parse_event_stub_from_fd(event_file_fd):
    """Read event with HTTP headers as CIMultiDict instance."""
    http_headers, event = _parse_fd_content(event_file_fd)
    return _transform_http_headers_list_to_multidict(http_headers), event


def validate_http_headers(headers):
    """Verify that HTTP headers look sane."""
    if headers['content-type'] != 'application/json':
        raise ValueError

    if not headers['user-agent'].startswith('GitHub-Hookshot/'):
        raise ValueError

    gh_delivery_lens = tuple(map(len, headers['x-github-delivery'].split('-')))
    if gh_delivery_lens != (8, 4, 4, 4, 12):
        raise ValueError

    if not isinstance(headers['x-github-event'], str):
        raise ValueError


def augment_http_headers(headers):
    """Add fake HTTP headers for the missing positions."""
    fake_headers = make_http_headers_from_event(headers['x-github-event'])

    if 'content-type' not in headers:
        headers['content-type'] = fake_headers['content-type']

    if 'user-agent' not in headers:
        headers['user-agent'] = fake_headers['user-agent']

    if 'x-github-delivery' not in headers:
        headers['x-github-delivery'] = fake_headers['x-github-delivery']

    return headers


def make_http_headers_from_event(event_name):
    """Generate fake HTTP headers with the given event name."""
    return multidict.CIMultiDict(**{
        'content-type': 'application/json',
        'user-agent': 'GitHub-Hookshot/fallback-value',
        'x-github-delivery': '49b0a670-63cd-11e9-8686-1a54dc9fb341',
        'x-github-event': event_name,
    })
