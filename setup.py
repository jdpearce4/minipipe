from setuptools import setup

long_description = """
MiniPipe is a mini-batch pipeline designed for training machine learning models on very large datasets in a streaming 
fashion, written in pure python. MiniPipe is designed for situations where the data are too large to fit into memory, 
or when doing so would discourage experiment iterations due to prohibitively long loading and/or processing times.
"""

setup(name='minipipe',
      version='0.1.9',
      description='A machine learning mini-batch pipeline for out-of-memory training',
      long_description=long_description,
      long_description_content_type="text/markdown",
      url='https://minipipe.readthedocs.io',
      author='James D. Pearce',
      author_email='jdp.pearce@gmail.com',
      license='MIT',
      #package_dir  = {'minipipe' : 'minipipe'},
      packages=['minipipe'],
      install_requires=[
          'graphviz',
      ],
      classifiers = [
	    "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
	],
      zip_safe=False)
