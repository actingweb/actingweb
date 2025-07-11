from setuptools import setup


def readme():
    with open('README.rst') as f:
        return f.read()


setup(
    name='actingweb',
    version='2.6.5',
    description='The official ActingWeb library',
    long_description=readme(),
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: System :: Distributed Computing',
    ],
    url='http://actingweb.org',
    author='Greger Wedel',
    author_email='support@greger.io',
    license='BSD',
    packages=[
        'actingweb',
        'actingweb.handlers',
        'actingweb.db_dynamodb'
    ],
    python_requires='>=3.11',
    install_requires=[
        'pynamodb>=6.0.0',
        'boto3>=1.26.0',
        'urlfetch>=1.0.2',
        'typing-extensions>=4.0.0'
    ],
    include_package_data=True,
    zip_safe=False)
