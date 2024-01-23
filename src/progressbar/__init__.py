# SPDX-FileCopyrightText: 2024 Geoffrey Lentner
# SPDX-License-Identifier: MIT

"""Display progress bar for streaming data."""


# Type annotations
from __future__ import annotations
from typing import List, Dict, Final, Callable, Iterable, IO, BinaryIO, Optional

# Standard libs
import os
import re
import sys
from importlib.metadata import version as get_version
from functools import cache, cached_property, partial

# External libs
from cmdkit.logging import Logger, level_by_name, logging_styles
from cmdkit.app import Application, exit_status
from cmdkit.cli import Interface, ArgumentError
from cmdkit.config import Configuration, ConfigurationError
from cmdkit.ansi import italic, COLOR_STDOUT, colorize_usage as default_colorize_usage
from tqdm import tqdm


# Metadata
PKGNAME: Final[str] = 'progressbar'
APPNAME: Final[str] = 'pb'
VERSION: Final[str] = get_version(PKGNAME)


# Global runtime configuration from environment variables
cfg = Configuration.from_local(env=True, prefix=APPNAME.upper(), default={
    'logging': {
        'level': 'warning',
        'style': 'default',
    },
    'stream': {
        'buffsize': '10M'
    },
})


# Logger used instead of progress bar if desired
log = Logger.default(name=APPNAME,
                     level=level_by_name[cfg.logging.level.upper()],
                     **logging_styles.get(cfg.logging.style.lower(), {}))


def print_exception(exc: Exception, status: int) -> int:
    """Log `exc` and return `status`."""
    log.critical(str(exc))
    return status


# Look-around pattern to negate matches within quotation marks
# Whole quotations are formatted together
NOT_QUOTED = (
    r'(?=([^"]*"[^"]*")*[^"]*$)' +
    r"(?=([^']*'[^']*')*[^']*$)" +
    r'(?=([^`]*`[^`]*`)*[^`]*$)'
)


def format_special_args(text: str) -> str:
    """Formatting special arguments."""
    metavars = ['COUNT', ]
    metavars_pattern = r'\b(?P<arg>' + '|'.join(metavars) + r')\b'
    return re.sub(metavars_pattern + NOT_QUOTED, italic(r'\g<arg>'), text)


def colorize_usage(text: str) -> str:
    """Apply additional formatting to usage/help text."""
    if not COLOR_STDOUT:
        return text
    else:
        return default_colorize_usage(format_special_args(text))


USAGE: Final[str] = f"""\
Usage:
  pb [-hV] [FILE [FILE...]] [-b SIZE] [-l [-t COUNT]] [-v | -d]
  {__doc__}\
"""

HELP: Final[str] = f"""\
{USAGE}

Arguments:
  FILE...               Paths to files (default: <stdin>).

Options:
  -l, --lines           Count lines instead of bytes.
  -t, --total    COUNT  Total lines expected (requires --lines).
  -b, --buffer   SIZE   Buffer size (default: 10M).
  -v, --verbose         Enable logging (disable progress bar).
  -d, --debug           Enable logging (conflicts with --verbose).
  -V, --version         Show version and exit.
  -h, --help            Show this message and exit.
"""


class PBar(Application):
    """Application interface for `pb` program."""

    interface = Interface(APPNAME, USAGE, HELP, formatter=colorize_usage)
    interface.add_argument('-V', '--version', action='version',
                           version=f'{APPNAME} v{VERSION}')

    paths: List[str] | None = None
    interface.add_argument('paths', nargs='*')

    feed_mode: str = 'bytes'
    buff_size: str = str(cfg.stream.buffsize)
    interface.add_argument('-b', '--buffer', default=buff_size, dest='buff_size')
    interface.add_argument('-l', '--lines', action='store_const', const='lines',
                           default=feed_mode, dest='feed_mode')

    total: Optional[str] = None
    interface.add_argument('-t', '--total', default=total)

    logging_level: str = cfg.logging.level
    logging_interface = interface.add_mutually_exclusive_group()
    logging_interface.add_argument('--logging', default=logging_level, dest='logging_level',
                                   choices=[name.lower() for name in level_by_name])
    logging_interface.add_argument('-v', '--verbose', action='store_const', const='info', dest='logging_level')
    logging_interface.add_argument('-d', '--debug', action='store_const', const='debug', dest='logging_level')

    log_critical = log.critical
    log_exception = log.exception

    exceptions = {
        ConfigurationError: partial(print_exception, status=exit_status.bad_config),
        RuntimeError: partial(print_exception, status=exit_status.runtime_error),
    }

    def run(self: PBar) -> None:
        """Stream files and display progress bar."""
        log.setLevel(level_by_name[cfg.logging.level.upper()])
        self.check_filepaths()
        for buff in self.read():
            sys.stdout.buffer.write(buff)

    @cached_property
    def read(self: PBar) -> Callable[[], Iterable[bytes]]:
        """Stream method chosen by command-line options."""
        return self.read_bytes if self.feed_mode == 'bytes' else self.read_lines

    def read_bytes(self: PBar) -> Iterable[bytes]:
        """Progress bar over bytes read."""
        with tqdm(total=self.get_total(),
                  unit='B',
                  unit_scale=True,
                  unit_divisor=1024,
                  file=self.pb_stream) as progress:
            for stream in self.iter_stream():
                progress.set_description(stream.name)
                while (buff := stream.read(self.buff_size_in_bytes)):
                    size = len(buff)
                    log.debug(f'Writing {size} bytes ({stream.name})')
                    progress.update(size)
                    yield buff

    def read_lines(self: PBar) -> Iterable[bytes]:
        """Progress bar over lines."""
        with tqdm(total=self.get_total(),
                  unit='Lines',
                  unit_scale=True,
                  file=self.pb_stream) as progress:
            for stream in self.iter_stream():
                progress.set_description(stream.name)
                while (buff := stream.read(self.buff_size_in_bytes)):
                    size, count = len(buff), buff.count(b'\n')
                    log.debug(f'Writing {size} bytes ({stream.name})')
                    progress.update(count)
                    yield buff

    @cached_property
    def pb_stream(self: PBar) -> IO:
        """IO stream to write progress bar."""
        if log.level < level_by_name['WARNING']:
            return open(os.devnull, mode='w')
        else:
            return sys.stderr

    def iter_stream(self: PBar) -> Iterable[BinaryIO]:
        """Yields file streams."""
        if not self.paths:
            log.info('Reading <stdin> (unknown size)')
            yield sys.stdin.buffer
        else:
            for path in self.paths:
                size = self.format_size(self.get_size(path))
                log.info(f'Reading file ({path}: {size})')
                with open(path, mode='rb') as stream:
                    yield stream

    def check_filepaths(self: PBar) -> None:
        """Ensure all file arguments exist."""
        if self.paths == ['-', ]:
            self.paths = None
        if self.paths:
            for path in self.paths:
                if not os.path.isfile(path):
                    raise ArgumentError(f'Not a file: {path}')

    BYTE_SCALE: Dict[str, int] = {
        '': 1,
        'k': 1024,
        'm': 1024 * 1024,
    }

    COUNT_SCALE: Dict[str, int] = {
        '':  1,
        'k': 1_000,
        'm': 1_000_000,
        'b': 1_000_000_000,
        't': 1_000_000_000_000,
    }

    @cached_property
    def buff_size_in_bytes(self: PBar) -> int:
        """Compute integer bytes from string (e.g., 10M)."""
        if (match := re.match('^(?P<value>[0-9]+)(?P<suffix>[a-z]?)(b)?$',
                              self.buff_size.lower())):
            value = int(match.group('value'))
            suffix = match.group('suffix') or ''
            if suffix in self.BYTE_SCALE:
                return value * self.BYTE_SCALE[suffix]
            if suffix in {'g', 't', 'p'}:
                raise ArgumentError(f'Buffer size too large: {self.buff_size}')
            else:
                raise ArgumentError(f'Unrecognized buffer size: {self.buff_size}')
        else:
            raise ArgumentError(f'Unrecognized buffer size: {self.buff_size}')

    @cache
    def get_total(self: PBar) -> Optional[int]:
        """Integer number as count of lines or total bytes for files requested."""
        if self.total:
            if (match := re.match('^(?P<value>[0-9]+)(?P<suffix>[a-z])?$',
                                  self.total.lower())):
                value = int(match.group('value'))
                suffix = match.group('suffix') or ''
                if suffix in self.COUNT_SCALE:
                    return value * self.COUNT_SCALE[suffix]
                else:
                    raise ArgumentError(f'Unrecognized total: {self.total}')
            else:
                raise ArgumentError(f'Unrecognized total: {self.total}')
        if not self.paths:
            return None
        if self.feed_mode == 'bytes':
            return sum(map(self.get_size, self.paths))

    @staticmethod
    @cache
    def get_size(path: str) -> int:
        """Cached version of `os.path.getsize`."""
        return os.path.getsize(path)

    @staticmethod
    def format_size(size: int) -> str:
        """Pretty-print size in bytes."""
        i = 0
        suffix = ('', 'K', 'M', 'G', 'T')
        v = float(size)
        while v > 1024:
            v /= 1024
            i += 1
        return f'{v:.1f}{suffix[i]}B'



def main(argv: List[str] | None = None) -> int:
    """Entry-point for `pb` program."""
    return PBar.main(argv or sys.argv[1:])

