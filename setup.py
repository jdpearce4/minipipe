from setuptools import setup

long_description = """
MiniPipe is a mini-batch pipeline designed for training machine learning models on very large datasets in a streaming 
fashion, written in pure python. MiniPipe is designed for situations where the data are too large to fit into memory, 
or when doing so would discourage experiment iterations due to prohibitively long loading and/or processing times.

Instead of a distributed approach to model training MiniPipe is designed around a streaming paradigm that utilizes 
pipeline parallelism. In the intended use case data are loaded from a data lake one 'chunk' at a time. Such an approach 
requires a training method that allows for iterative training on small batches of data (mini-batches) such as stochastic
 gradient decent.

A MiniPipe pipeline is build up from pipe segments, which may be connected to form a DAG. In the general case, each pipe 
segments has two queues, one for accepting upstream data (inputs) and another for passing data downstream (outputs). 
All pipe segments run on their own process which allows for asynchronous pipeline parallelization (see figure below). 
Such parallelization can dramatically increase the throughput of a pipeline and reduce training/processing times.
"""

setup(name='minipipe',
      version='0.1.3',
      description='A machine learning mini-batch pipeline for out-of-memory training',
      long_description=long_description,
      long_description_content_type="text/markdown",
      url='https://github.com/jdpearce4/minipipe',
      author='James D. Pearce',
      author_email='jdp.pearce@gmail.com',
      license='MIT',
      package_dir  = {'minipipe' : 'src'},
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
