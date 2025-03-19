# SPOTA

## Helps you hunt SOTA/POTA

Real docs coming later. Maybe. Or just RTSL.

This is a text-mode curses program that helps you hunt SOTA and POTA. Every sixty seconds, the program uses the SOTA/POTA APIs to grab the latest spots and displays them on the screen. You have the choice of viewing SOTA, POTA, or both (use the 's' key). You can sort them by frequency or by time (use the 'o' key). Use the vi keys (j/k) to move up and down the list. Use the 't' key to tune your transceiver (and set the mode) to the current spot. If you work a station, hit 'w'. If you can hear a station, but can't/didn't work it, hit 'h' (so you know to go back to it later). If you can't hear a station, hit 'c' (noting that you can't hear it).

For now, you have to edit the script directly and set your radio model, serial port, and serial speed in the code itself (near the bottom). This will be added to a configuration file at some point to make it easier (or specified on the command line, not sure yet).

Note that all actions are logged in /tmp/spota.log, so you can pull out the worked stations and log them yourself. At some point, I may (or may not, depends on what's supported in the SOTA/POTA APIs) add the ability to log directly from the program.

It's still a work in progress, but it makes it easier to hunt.

This has been tested and works well on Linux, and there's no reason to believe it wouldn't work equally well on a Mac. I suspect it'll work on Windows, but... Well, maybe. I dunno. You might have to modify the path for the log file, as there's no /tmp/ directory on Windows. YMMV.

You must install the hamlib, mmh3, and argparse python libraries for this to work. I think all of the other libraries are included by default in python3.

Jeff/N0GQ
