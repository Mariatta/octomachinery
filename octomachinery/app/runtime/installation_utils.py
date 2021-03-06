"""Utility helpers for App/Action installations."""

from base64 import b64decode
from io import StringIO
from pathlib import Path
import typing

import yaml

from .context import RUNTIME_CONTEXT


def _get_file_contents_from_fs(file_name: str) -> typing.Optional[str]:
    """Read file contents from file system checkout.

    This code path is synchronous.

    It doesn't matter much in GitHub Actions
    but can be refactored later.
    """
    config_path = (Path('.') / file_name)

    try:
        return config_path.read_text()
    except FileNotFoundError:
        return None


async def _get_file_contents_from_api(
        file_name: str,
        ref: typing.Optional[str],
) -> typing.Optional[str]:
    """Read file contents using GitHub API."""
    github_api = RUNTIME_CONTEXT.app_installation_client
    repo_slug = RUNTIME_CONTEXT.github_event.data['repository']['full_name']

    api_query_params = f'?ref={ref}' if ref else ''
    config_response = await github_api.getitem(
        f'/repos/{repo_slug}/contents'
        f'/{file_name}{api_query_params}',
    )

    config_file_found = (
        config_response.get('encoding') == 'base64' and
        'content' in config_response
    )
    if not config_file_found:
        return None

    return b64decode(config_response['content']).decode()


async def get_installation_config(
        *,
        config_name: str = 'config.yml',
        ref: typing.Optional[str] = None,
) -> typing.Mapping[str, typing.Any]:
    """Get a config object from the current installation.

    Read from file system checkout in case of GitHub Action env.
    Grab it via GitHub API otherwise.

    Usage::

        >>> from octomachinery.app.runtime.installation_utils import (
        ...     get_installation_config
        ... )
        >>> await get_installation_config()
    """
    config_path = f'.github/{config_name}'

    if RUNTIME_CONTEXT.IS_GITHUB_ACTION and ref is None:
        config_content = _get_file_contents_from_fs(config_path)
    else:
        config_content = await _get_file_contents_from_api(config_path, ref)

    if config_content is None:
        return {}

    return yaml.load(StringIO(config_content))
