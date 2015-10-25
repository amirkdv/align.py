#!/usr/bin/env python

from setuptools import setup, find_packages
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md')) as f:
    long_description = f.read()

setup(
    name='align.py',
    version='0.0.1',
    description='A library for sequence alignment',
    long_description=long_description,
    url='https://github.com/amirkdv/align.py',
    author='Amir Kadivar',
    author_email='amir@amirkdv.ca',
    #license='MIT',
    #keywords='sequence alignment',
    packages=['align'],
    install_requires=['biopython', 'termcolor', 'numpy', 'cffi'],
)
