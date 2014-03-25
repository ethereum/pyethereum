import logging
import logging.config
from ConfigParser import ParsingError
import sys


if not 'logging' in sys.modules:  # Defensively avoid to override external logging-configurations (e.g. when imported as a library).
    try:
        logging.config.fileConfig('logging.conf')
    except ParsingError as e:
        print "no usable logging.conf (Error: \"%s\") -> will log to stdout" % e
        logging.basicConfig(format='[%(asctime)s] %(name)s %(levelname)s %(message)s', level=logging.DEBUG)

logger = logging.getLogger(__name__)

logger.debug('logging set up')
