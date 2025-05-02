from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="chronos",
    version="1.0.0",
    author="a-curious-coder",
    description="A tool to check domain expiration dates",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/a-curious-coder/chronos",
    packages=find_packages(),
    python_requires=">=3.12",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "check-domains=dns_domain_expiration_checker:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Operating System :: OS Independent",
    ],
)