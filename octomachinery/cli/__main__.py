#! /usr/bin/env python3
"""Octomachinery CLI entrypoint."""

import asyncio
import importlib
import json
import os
import pathlib
import tempfile

import click

from ..app.action.runner import run as process_action
from .utils import (
    augment_http_headers, make_http_headers_from_event,
    parse_event_stub_from_fd, validate_http_headers,
)


@click.group()
@click.pass_context
def cli(ctx):
    """Click CLI base."""
    pass


@cli.command()
@click.option('--event', '-e', prompt=True, type=str)
@click.option('--payload-path', '-p', prompt=True, type=click.File(mode='r'))
@click.option('--token', '-t', prompt=True, type=str)
@click.option('--app', '-a', prompt=True, type=int)
@click.option('--private-key', '-P', prompt=True, type=click.File(mode='r'))
@click.option('--entrypoint-module', '-m', prompt=True, type=str)
@click.pass_context
def receive(
        ctx,
        event, payload_path,
        token,
        app, private_key,
        entrypoint_module,
):
    """Webhook event receive command."""
    app_missing_private_key = app is not None and not private_key
    if app_missing_private_key:
        ctx.fail('App requires a private key')

    creds_present = token or (app and private_key)
    if not creds_present:
        ctx.fail('Any GitHub auth credentials are missing')

    too_many_creds_present = token and (app or private_key)
    if not too_many_creds_present:
        ctx.fail(
            'Please choose between a token or an app id with a private key',
        )

    http_headers, event_data = parse_event_stub_from_fd(payload_path)

    if event and http_headers:
        ctx.fail('Supply only one of an event name or an event fixture file')

    if http_headers:
        http_headers = augment_http_headers(http_headers)
        event = http_headers['x-event-event']
    else:
        http_headers = make_http_headers_from_event(event)
    validate_http_headers(http_headers)

    if app is None:
        _process_event_as_action(
            event, event_data,
            token,
            entrypoint_module,
        )
    else:
        asyncio.run(_process_event_as_app(
            http_headers, event_data,
            app, private_key,
            entrypoint_module,
        ))


def _process_event_as_action(
        event, event_data,
        token,
        entrypoint_module,
):
    os.environ['OCTOMACHINERY_APP_MODE'] = 'action'

    os.environ['GITHUB_ACTION'] = 'Fake CLI Action'
    os.environ['GITHUB_ACTOR'] = event_data['sender']['login']
    os.environ['GITHUB_EVENT_NAME'] = event
    os.environ['GITHUB_WORKSPACE'] = str(pathlib.Path('.').resolve())
    os.environ['GITHUB_SHA'] = event_data['head_commit']['id']
    os.environ['GITHUB_REF'] = event_data['ref']
    os.environ['GITHUB_REPOSITORY'] = event_data['repository']['full_name']
    os.environ['GITHUB_TOKEN'] = token
    os.environ['GITHUB_WORKFLOW'] = 'Fake CLI Workflow'

    with tempfile.NamedTemporaryFile(
            suffix='.json', prefix='github-workflow-event-',
    ) as tmp_event_file:
        json.dump(tmp_event_file, event_data)
        os.environ['GITHUB_EVENT_PATH'] = tmp_event_file.name
        importlib.import_module(entrypoint_module)
        process_action()


async def _process_event_as_app(
        http_headers, event_data,
        app, private_key,
        entrypoint_module,
):
    os.environ['OCTOMACHINERY_APP_MODE'] = 'app'

    os.environ['GITHUB_APP_IDENTIFIER'] = app
    os.environ['GITHUB_PRIVATE_KEY'] = private_key.read()

    importlib.import_module(entrypoint_module)
    from ..app.routing.webhooks_dispatcher import route_github_webhook_event
    from ..app.runtime.context import RUNTIME_CONTEXT
    from ..app.github.api.app_client import GitHubApp
    from ..app.config import BotAppConfig
    from aiohttp.web_request import Request
    config = BotAppConfig.from_dotenv()
    from aiohttp.http_parser import RawRequestMessage
    import yarl

    class protocol_stub:
        transport = None
    message = RawRequestMessage(
        'POST', '/', 'HTTP/1.1',
        http_headers,
        None, None, None, None, None,
        yarl.URL('/'),
    )
    http_request = Request(
        message=message,
        payload=None,  # dummy
        protocol=protocol_stub(),
        payload_writer=None,  # dummy
        task=None,  # dummy
        loop=asyncio.get_running_loop(),
    )

    async def read_coro():
        return event_data
    http_request.read = read_coro
    async with GitHubApp(config.github) as github_app:
        RUNTIME_CONTEXT.github_app = (  # pylint: disable=assigning-non-slot
            github_app
        )
        route_github_webhook_event(http_request)


def main():
    """CLI entrypoint."""
    return cli(obj={}, auto_envvar_prefix='OCTOMACHINERY_CLI_')


__name__ == '__main__' and main()
