from setuptools import setup

setup(name='actingweb',
      version='2.1.2',
      description='The official ActingWeb library',
      url='http://actingweb.org',
      author='Greger Wedel',
      author_email='greger@support.io',
      license='BSD',
      packages=[
            'actingweb',
            'actingweb.handlers',
            'actingweb.db_gae',
            'actingweb.db_dynamodb'
      ],
      python_requires='<3',
      install_requires=[],
      include_package_data=True,
      zip_safe=False)