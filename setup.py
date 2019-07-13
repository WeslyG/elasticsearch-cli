from setuptools import setup, find_packages

setup(
    name='elasticsearch-cli',
    version='1.0.1',
    license='MIT',
    author="Wesly Allan",
    author_email="weslyg22@gmail.com",
    description="Elasticsearch cli",
    url="https://github.com/WeslyG/elasticsearch-cli",
    download_url='https://github.com/WeslyG/elasticsearch-cli/releases/download/1.0.1/elasticsearch-cli-1.0.1.tar.gz',
    packages=find_packages(),
    install_requires=[
        'Click',
        'Elasticsearch'
    ],
    classifiers=[
        "Programming Language :: Python :: Implementation",
        "Natural Language :: English",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    entry_points='''
        [console_scripts]
        es=main:cli
    ''',
)
