from setuptools import setup

setup(
    name='elasticsearch-cli',
    version='1.0.0',
    license='MIT',
    author="Wesly Allan",
    author_email="weslyg22@gmail.com",
    description="Elasticsearch cli",
    url="https://github.com/WeslyG/elasticsearch-cli",
    download_url='https://github.com/WeslyG/elasticsearch-cli/dist/elasticsearch-cli-1.0.0.tar.gz',
    py_modules=['main'],
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
