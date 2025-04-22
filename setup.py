#!/usr/bin/env python
# setup.py

import pathlib
from setuptools import setup, find_packages

HERE = pathlib.Path(__file__).parent

# long_description from your README
long_description = (HERE / "README.md").read_text(encoding="utf-8")

setup(
    name="aiorexense",
    version="0.1.0",
    description="Rexense device client library with HTTP API and WebSocket support",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Zhejiang Rexense IoT Technology Co., Ltd",
    license="MIT License",
    package_dir={"aiorexense": "src"},
    packages=["aiorexense"],
    include_package_data=True,
    package_data={"aiorexense": ["py.typed"]},
    url="https://github.com/RexenseIoT/aiorexense.git",  # adjust as needed
    python_requires=">=3.8",
    install_requires=[
        "aiohttp>=3.8.0",
    ],
    # since your modules live at the top level:
    py_modules=["api", "const", "ws_client"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
