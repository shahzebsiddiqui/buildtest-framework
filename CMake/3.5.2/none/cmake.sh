#!/bin/sh

module purge
module=CMake
version=3.5.2
module load $module/$version

if [ $? != 0 ]; then
	echo "unable to load module $module/$version"
	exit 1
fi

cmake --version
if [ $? != 0 ]; then
	echo "Unable to run cmake "
	exit 1
fi

