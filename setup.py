from setuptools import setup


def readme():
    with open('README.rst') as f:
        return f.read()


setup(
    name='actingweb',
    version='2.4.0',
    description='The official ActingWeb library',
    long_description=readme(),
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
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
    python_requires='>=2.7',
    install_requires=[
        'pynamodb',
        'boto3',
        'urlfetch',
        'future'
    ],
    include_package_data=True,
    zip_safe=False)
