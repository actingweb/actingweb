from setuptools import setup


def readme():
    with open('README.rst') as f:
        return f.read()


setup(name='actingweb',
      version='2.3.0',
      description='The official ActingWeb library',
      long_description=readme(),
      classifiers=[
            'Development Status :: 5 - Production/Stable',
            'Intended Audience :: Developers',
            'License :: OSI Approved :: BSD License',
            'Programming Language :: Python :: 2.7',
            'Topic :: System :: Distributed Computing',
      ],
      url='http://actingweb.org',
      author='Greger Wedel',
      author_email='greger@support.io',
      license='BSD',
      packages=[
            'actingweb',
            'actingweb.handlers',
            'actingweb.db_dynamodb'
      ],
      python_requires='<3',
      install_requires=[
            'pynamodb',
            'boto3',
            'urlfetch'
      ],
      include_package_data=True,
      zip_safe=False)
