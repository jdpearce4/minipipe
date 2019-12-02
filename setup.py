from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(name='minipipe',
      version='0.1.2',
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
