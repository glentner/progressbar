pb
==

Command-line progress bar for streaming files or lines of text.
This is simply an alternate front-end to [tqdm](https://github.com/tqdm/tqdm).

Install
-------

```sh
pipx install git+https://github.com/glentner/progressbar.git
```

Or on macOS

```sh
brew tap glentner/tap
brew install pb
```

Usage
-----

Use `pb --help` to get usage and help on options.
The default behavior is to display a progress bar of bytes streamed.
Positional arguments are paths to files; without any arguments we stream from `stdin`.
We get the total bytes expected by asking the file system for the size of the files.
If streaming from `stdin` we simply display current stats without the progress bar.

The output is entirely provided by [tqdm](https://github.com/tqdm/tqdm).
To count lines instead of bytes, use `--lines`.
Without a `--total` we only display stats as with `stdin`.
The `-b`, `--buffer` option is allowed in either case.
We choose an extremely large default buffer size on purpose.

Specifying counts can be explicit or with a suffix, e.g., `16K` or `10M`.
Specifying buffer size can be explicit or with a suffix, e.g., `512KB`.

Enable logging messages as an alternative to the progress bar by
using either `-v` or `-d` for INFO and DEBUG levels, respectively.
For lots of small files `-v` is appropriate; for a few large files,
`-d` will show individual buffer writes.

Why
---

I love [tqdm](https://github.com/tqdm/tqdm) but the default behavior makes
streaming files very tedious, this is a shorter syntax and automatically
computes the total size of files on disk.

Examples
--------

Stream log messages from directory:

```sh
ls messages/*.gz | sort | xargs pb | gunzip | ...
```

Stream 1 billion rows from file ([https://1brc.dev](https://1brc.dev)):

```
pb measurements.txt -l -t 1B | ./1brc -
```

Contributing
------------

This is finished software made for a narrow purpose.
If you find a bug or think something obvious is missing,
please feel free to open an issue or pull request with a fix.

