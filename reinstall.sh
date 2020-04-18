rm -rf dist
rm -rf minipipe.egg*
python setup.py sdist
pip install .
