sudo apt-get update

sudo apt-get install python-virtualenv

sudo apt-get install python-dev -y --fix-missing
sudo apt-get install -y build-essential
sudo apt-get install pkg-config
sudo apt-get install libffi-dev
sudo apt-get install -y autoconf
sudo apt-get install automake -y
sudo apt-get install python -y
sudo apt-get install -y libtool
sudo apt-get install python-pip git
sudo apt-get install python-pip -y --fix-missing
sudo apt-get install -y --fix-missing git
sudo apt-get install openssl-dev
sudo apt-get install libssl-dev
sudo apt-get install supervisor

virtualenv guardian
source guardian/bin/activate

pip install setuptools --upgrade

git clone https://github.com/pipermerriam/serpent.git
ct serpent && git checkout develop && python setup.py develop

git clone https://github.com/pipermerriam/pydevp2p.git
cd pydevp2p && python setup.py develop

git clone https://github.com/ethereum/pyrlp.git
cd pyrlp && python setup.py develop

pip install leveldb
pip install numpy

git clone https://github.com/pipermerriam/pyethereum.git
cd pyethereum && git checkout piper/serenity-run-independent-guardian-node && python setup.py develop

python ethereum/run_test_guardian.py --key-idx 0 --generate-genesis 1
