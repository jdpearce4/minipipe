MiniPipe: A mini-batch pipeline
===============================

MiniPipe is a mini-batch pipeline designed for training machine learning models on very large datasets in a streaming
fashion, written in pure python. MiniPipe is designed for situations where the data are too large to fit into memory,
or when doing so would discourage experiment iterations due to prohibitively long loading and/or processing times.

Instead of taking a distributed approach to model training MiniPipe is designed around a streaming approach. In the
intended use case data are loaded from a data lake one 'chunk' at a time. Such an approach requires a training paradigm
that allows for iterative training on small batches of data (mini-batches) such as stochastic gradient decent.

A mini-batch pipeline is build up from pipe segments, which may be connected to form a DAG. In the general case, each
pipe segments has two queues, one for accepting upstream data (inputs) and another for passing data downstream (outputs).
All segments are capable of running on their own thread or process which allows for asynchronous pipeline parallelization.
As we'll see, such parallelization can dramatically increase the throughput of a pipeline and reduce training/processing
times.

The goal of MiniPipe is to encourage experimentation and prototyping at full data scale by making complex training
pipelines simple, flexible and fast. The look and feel of the Minipipe API is based on the very successful Keras Model
API, which strikes a good balance between simplicity and flexibility.

Installation
------------
Installation is super easy with *pip*:
```
pip install minipipe
```