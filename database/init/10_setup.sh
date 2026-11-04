#!/bin/sh
# Official postgres image runs this once, on first start with an empty volume.
sh /database/setup.sh
