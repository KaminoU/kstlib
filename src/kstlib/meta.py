"""Metadata and constants for kstlib package.

This module defines the package metadata including name, version, author information,
and ASCII art logo used in CLI output.
"""

__logo__ = (
    """
{{ FRM }}##################################################################################################    {{ G }}###    {{ R }}###    {{ FRM }}####
##################################################################################################    {{ G }}###    {{ R }}###    {{ FRM }}####
##                                                                                                                    ##
##             {{ R }}##################   .#######:     {{ G }}.######.     {{ R }}##########################################             {{ FRM }}##
##             {{ R }}##################..#########.   {{ G }}.#########.    {{ R }}##########################################             {{ FRM }}##
##             {{ R }}###           ########.         {{ G }}:###########:                                          {{ R }}###             {{ FRM }}##
##             {{ R }}###           ######.           {{ G }}.##########:.                                          {{ R }}###             {{ FRM }}##
##             {{ R }}###           ####.            {{ G }}.#########:.                                            {{ R }}###             {{ FRM }}##
##             {{ R }}###           ##.            {{ G }}.#######                                                  {{ R }}###             {{ FRM }}##
##             {{ R }}###           "            {{ G }}.######                                                     {{ R }}###             {{ FRM }}##
##             {{ R }}###                     {{ G }}.:######                                           {{ R }}###############             {{ FRM }}##
##             {{ R }}###                 {{ G }}.##########:.                .:#######.                {{ R }}###############             {{ FRM }}##
##             {{ R }}###               {{ G }}:########################################.               {{ R }}###                         {{ FRM }}##
##             {{ R }}###              {{ G }}:################# {{ FRM }}L I B {{ G }}##################:              {{ R }}###                         {{ FRM }}##
##             {{ R }}###               {{ G }}.########################################.               {{ R }}###                         {{ FRM }}##
##             {{ R }}###                 {{ G }}:######:.                 ###########.                 {{ R }}###                         {{ FRM }}##
##             {{ R }}###                                         {{ G }}:######:.                      {{ R }}###                         {{ FRM }}##
##             {{ R }}###           .                           {{ G }}:######:.           {{ R }}.            ###                         {{ FRM }}##
##             {{ R }}###           ##                       {{ G }}.:######.             {{ R }}##            ###                         {{ FRM }}##
##             {{ R }}###           ####                {{ G }}.:#########.              {{ R }}###            ###                         {{ FRM }}##
##             {{ R }}###           ######             {{ G }}:###########:              {{ R }}###            ###                         {{ FRM }}##
##             {{ R }}###           ########           {{ G }}:###########:              {{ R }}###            ###                         {{ FRM }}##
##             {{ R }}##################..##########.  {{ G }}":#########"               {{ R }}##################                         {{ FRM }}##
##             {{ R }}##################  .#########:   {{ G }}":######:"                {{ R }}##################                         {{ FRM }}##
##                                                                                                                    ##
###################################################################################################[ Michel TRUONG ]####
########################################################################################################################
""".replace("{{ FRM }}", "[bright_black]")
    .replace("{{ G }}", "[chartreuse2]")
    .replace("{{ R }}", "[deep_pink2]")
)

__app_name__ = "kstlib"
__version__ = "1.0.0"
__description__ = (
    "Config-driven helpers for Python projects (dynamic config, secure secrets, preset logging, and more…)"
)
__author__ = "Michel TRUONG"
__email__ = "michel.truong@gmail.com"
__url__ = "https://kstlib.io"
__keywords__ = ["kstlib"]
__classifiers__ = [
    "Development Status :: 5 - Production/Stable",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
]
__license_type__ = "MIT"
__license__ = """
MIT License

Copyright © • 2025 • Michel TRUONG

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""
