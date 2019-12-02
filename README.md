# MiniPipe: A mini-batch pipeline

MiniPipe is a mini-batch pipeline designed for training machine learning models on very large datasets in a streaming
fashion, written in pure python. MiniPipe is designed for situations where the data are too large to fit into memory,
or when doing so would discourage experiment iterations due to prohibitively long loading and/or processing times.

Instead of a distributed approach to model training MiniPipe is designed around a streaming paradigm that utilizes 
pipeline parallelism. In the intended use case data are loaded from a data lake one 'chunk' at a time. Such an approach 
requires a training method that allows for iterative training on small batches of data (mini-batches) such as 
stochastic gradient decent.

A MiniPipe pipeline is build up from pipe segments, which may be connected to form a DAG. In the general case, each
pipe segments has two queues, one for accepting upstream data (inputs) and another for passing data downstream (outputs).
All pipe segments run on their own process which allows for asynchronous pipeline parallelization (see figure below).
Such parallelization can dramatically increase the throughput of a pipeline and reduce training/processing times.

Searial Pipeline             |  Pipeline Parallel
:-------------------------:|:-------------------------:
![](docs/source/images/toy_example_serial.png)  |  ![](docs/source/images/toy_example_parallel.png)

Additionally MiniPipe allows for horizontal parallelism, allowing for multiple processes to be assigned to bottleneck. 
For example, if in the above diagram Transform turns is slower than load and save multiple processes may be assigned to it. 

Horizonal Parallelism |
:-------------------------:
![](docs/source/images/toy_example_parallel_horizonal.png) 

MiniPipe is flexible allowing for generic graph topologies to fit any workflow. In the development cycle of machine 
learning models its often necessary to train multiple models to test out different hyperparameters, feature sets, 
preprocessing or variations on the model itself. 

Consider the scenario of hyperparameter tunning where one would like to test out multiple models that use the same 
training set and preprocessing. It would be inefficient to have a separate pipeline for each model since you'd need to
loading and preprocessing the same data multiple times. Instead one could use MiniPipe to set up a pipeline that loads 
processes the data once but feeds the result to multiple GPUs for training as shown below. 

Multi-model Training Pipeline |
:-------------------------: 
![](docs/source/images/multigpu_training_pipeline.png)

This is just one example of many possible pipelines that can make your machine learning workflow more efficient. See our 
[documentation](https://minipipe.readthedocs.io) pages for more examples. 

The goal of MiniPipe is to encourage experimentation and prototyping at full data scale by making complex training
pipelines simple, flexible and fast. The look and feel of the Minipipe API is based on the very successful Keras Model
API, which strikes a good balance between simplicity and flexibility.

## Installation
Installation is super easy with *pip*
```sh
pip install minipipe
```