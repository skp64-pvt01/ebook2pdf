"""Setup script for ebook2pdf."""

from setuptools import setup, find_packages

setup(
    name="ebook2pdf",
    version="1.0.0",
    description="EPUB to PDF converter with comprehensive formatting fixes",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Hermes Agent",
    python_requires=">=3.10",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    include_package_data=True,
    package_data={"ebook2pdf": ["data/*.css"]},
    entry_points={
        "console_scripts": [
            "ebook2pdf=ebook2pdf.cli:run_cli",
        ],
    },
    install_requires=[
        "pypdf>=5.0.0",
        'fitz; platform_system!="Linux"',
    ],
    extras_require={
        "font-audit": ["pymupdf>=1.23.0"],
        "pymupdf": ["pymupdf>=1.23.0"],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Desktop Publishing",
    ],
)
