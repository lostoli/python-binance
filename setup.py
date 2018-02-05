#!/usr/bin/env python
from setuptools import setup

setup(
    name='python-binance',
    version='0.6.2',
    packages=['binance'],
    description='Binance REST API python implementation',
    url='https://github.com/sammchardy/python-binance',
    author='Sam McHardy',
    license='MIT',
    author_email='',
    install_requires=['requests', 'six', 'Twisted', 'pyOpenSSL', 'autobahn', 'service-identity'],
    keywords='binance exchange rest api bitcoin ethereum btc eth neo',
    classifiers=[
          'Intended Audience :: Developers',
          'License :: OSI Approved :: MIT License',
          'Programming Language :: Python :: 3.6',
          'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
