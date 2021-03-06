import json
import logging
import os

from tabulate import tabulate
from jsonschema.exceptions import ValidationError
from buildtest.buildsystem.parser import BuildspecParser
from buildtest.config import load_settings
from buildtest.defaults import BUILDSPEC_CACHE_FILE, BUILDSPEC_DEFAULT_PATH
from buildtest.exceptions import BuildTestError
from buildtest.utils.file import is_dir, is_file, walk_tree, resolve_path, read_file

logger = logging.getLogger(__name__)


class BuildspecCache:

    table = {}
    filter_fields = ["type", "executor", "tags"]
    default_format_fields = ["name", "type", "executor", "tags", "description"]
    format_fields = default_format_fields + ["file"]

    def __init__(self, rebuild, filterfields, formatfields, roots):
        """The initializer method for BuildspecCache class is responsible for
        loading and finding buildspecs into buildspec cache. This method is called
        when using ``buildtest buildspec find`` command.

        :param rebuild: rebuild the buildspec cache by validating all buildspecs. The --rebuild is passed to this argument
        :type rebuild: bool, required
        :param filterfields:  The --filter option contains list of key value pairs for filtering buildspecs
        :type filterfields: str, required
        :param formatfields: The --format option contains list of key value pairs for formating buildspecs
        :type formatfields: str, required
        :param roots:  List of directories to search for buildspecs. This argument contains value of --roots
        :type roots: list, required
        """
        self.filter = filterfields
        self.format = formatfields
        # if --root is not specified we set to empty list instead of None
        self.roots = roots or []

        # list of buildspec directories to search for .yml files
        self.paths = []

        self.rebuild = rebuild
        self.cache = {}

        self.load_paths()
        self.build()

        self.check_filter_fields()
        self.check_format_fields()
        self.find_buildspecs()

    def get_cache(self):
        """Returns cache file as loaded dictionary"""

        return self.cache

    def load_paths(self):
        """Add all paths to search for buildspecs. We must read configuration file
        and check property ``buildspec_roots`` for list of directories to search.
        We check all directories exist, if any fail we don't add them to path.
        In addition, we add the default buildspec path where we find tutorials
        and general tests.
        """

        config_opts = load_settings()
        buildspec_paths = config_opts.get("buildspec_roots") or []

        if buildspec_paths:
            self.roots += buildspec_paths

        # only load default buildspecs if 'load_default_buildspecs' set to True
        if config_opts.get("load_default_buildspecs"):
            self.paths += BUILDSPEC_DEFAULT_PATH

        # for every root buildspec defined in configuration or via --root option,
        # we resolve path and if path exist add to self.paths. The path must be a
        # directory. If its file, we ignore it
        if self.roots:

            for root in self.roots:
                path = resolve_path(root, exist=False)
                if not os.path.exists(path):
                    print(f"Path: {path} does not exist!")

                if is_file(path):
                    print(f"Path: {path} must be a directory not a file")

                if is_dir(path):
                    self.paths.append(path)

    def build(self):
        """This method will build buildspec cache file. If user requests to
        rebuild cache we remove the file and recreate cache. If cache file
        exists, we simply load from cache
        """

        # implements buildtest buildspec find --rebuild which removes cache file
        # before finding all buildspecs. We only remove file if file exists
        if self.rebuild and is_file(BUILDSPEC_CACHE_FILE):
            try:
                os.remove(BUILDSPEC_CACHE_FILE)
                print(f"Clearing cache file: {BUILDSPEC_CACHE_FILE}")
            except OSError as msg:
                raise BuildTestError(msg)

        # if cache file is not found, then we will build cache by searching
        # all buildspecs paths and traverse directory to find all .yml files

        if not is_file(BUILDSPEC_CACHE_FILE):
            self.build_cache()

        with open(BUILDSPEC_CACHE_FILE, "r") as fd:
            self.cache = json.loads(fd.read())

    def _discover_buildspecs(self):
        """This method retrieves buildspecs based on ``self.paths`` which is a
        list of directory paths to search. If ``--root`` is specified
        we process each argument and recursively find all .yml files
        """

        buildspecs = []
        # add all buildspecs from each repo. walk_tree will find all .yml files
        # recursively and add them to list

        if not self.paths:
            raise BuildTestError(
                "Unable to search any buildspecs, please specify a directory"
            )

        if self.paths:
            for path in self.paths:
                buildspec = walk_tree(path, ".yml")
                buildspecs += buildspec

        print(f"\nBuildspec Paths: {self.paths} \n")

        return buildspecs

    def _write_buildspec_cache(self):
        """This method is responsible for writing buildspec cache to file"""

        with open(BUILDSPEC_CACHE_FILE, "w") as fd:
            json.dump(self.update_cache, fd, indent=2)

        print("\n")
        print("Invalid buildspecs")
        print("{:_<80}".format(""))
        for file in self.invalid_buildspecs:
            print(file)

        print(f"Found {len(self.invalid_buildspecs)} invalid buildspecs")
        print("{:_<80}".format(""))

        print("\n\n")
        print(f"Updating buildspec cache file: {BUILDSPEC_CACHE_FILE}")
        # write invalid buildspecs to file if any found
        if self.invalid_buildspecs:
            buildspec_error_file = os.path.join(
                os.path.dirname(BUILDSPEC_CACHE_FILE), "buildspec.error"
            )

            with open(buildspec_error_file, "w") as fd:
                for file, msg in self.invalid_buildspecs.items():

                    fd.write(f"buildspec file: {file} \n")
                    fd.write("Content of buildspec: \n")
                    fd.write("{:_<80} \n".format(""))
                    content = read_file(file)
                    fd.write(content)
                    fd.write("{:_<80} \n".format(""))
                    fd.write("\n")
                    fd.write("Error Message: \n")
                    fd.write(f"{msg}")
                    fd.write("\n\n")
                    fd.write("{:=<80} \n".format(""))

            print(f"Writing invalid buildspecs to file: {buildspec_error_file} ")

        print("\n\n")

    def _validate_buildspecs(self, buildspecs):
        """Given a list of buildspec files, validate each buildspec using BuildspecParser
        and return a list of valid buildspecs. Any invalid buildspecs are added to
        separate list
        """
        valid_buildspecs = []
        self.count = 0
        for buildspec in buildspecs:
            self.count += 1

            try:
                parse = BuildspecParser(buildspec)
            # any buildspec that raises SystemExit or ValidationError imply
            # buildspec is not valid, we add this to invalid list along with
            # error message and skip to next buildspec
            except (BuildTestError, ValidationError) as err:
                self.invalid_buildspecs[buildspec] = err
                continue

            valid_buildspecs.append(parse)

            if self.count % 5 == 0:
                print(f"Validated {self.count}/{len(buildspecs)} buildspecs")

        print(f"Validated {self.count}/{len(buildspecs)} buildspecs")
        return valid_buildspecs

    def build_cache(self):
        """This method will rebuild the buildspec cache file by recursively searching
        all .yml files specified by input argument ``paths`` which is a list of directory
        roots. The buildspecs are validated and cache file is updated"

        :param paths: A list of directory roots to process buildspecs files.
        :type paths: list
        :return: Rebuild cache file
        """

        self.update_cache = {}
        self.update_cache["unique_tags"] = []
        self.update_cache["unique_executors"] = []
        self.update_cache["buildspecs"] = {}
        self.update_cache["executor"] = {}
        self.update_cache["tags"] = {}
        self.update_cache["maintainers"] = {}

        self.invalid_buildspecs = {}

        for path in self.paths:
            self.update_cache[path] = {}

        buildspecs = self._discover_buildspecs()
        print("Discovered Buildspecs")
        print("{:_<80}".format(""))
        for file in buildspecs:
            print(file)

        print(f"Found {len(buildspecs)} buildspecs ")
        print("{:_<80}".format(""))
        print("\n")

        # validate each buildspec and return a list of valid buildspec parsers that
        # is an instance of BuildspecParser class
        parsers = self._validate_buildspecs(buildspecs)

        # for every parsers (valid buildspecs) we update cache to build an index
        for parser in parsers:

            recipe = parser.recipe["buildspecs"]

            # if maintainer field specified add all maintainers from buildspec to list
            if parser.recipe.get("maintainers"):
                print(parser.buildspec, parser.recipe["maintainers"])

                for author in parser.recipe["maintainers"]:
                    if not self.update_cache["maintainers"].get(author):
                        self.update_cache["maintainers"][author] = []

                    self.update_cache["maintainers"][author].append(parser.buildspec)

            if not self.update_cache["buildspecs"].get(parser.buildspec):
                self.update_cache["buildspecs"][parser.buildspec] = {}

            for name in recipe.keys():

                self.update_cache["buildspecs"][parser.buildspec][name] = recipe[name]
                tags = recipe[name].get("tags")
                executor = recipe[name].get("executor")
                description = recipe[name].get("description")

                if tags:

                    if isinstance(tags, str):
                        self.update_cache["unique_tags"].append(tags)

                        if not self.update_cache["tags"].get(tags):
                            self.update_cache["tags"][tags] = {}

                        self.update_cache["tags"][tags][name] = description

                    elif isinstance(tags, list):
                        self.update_cache["unique_tags"] += tags

                        # for every tagname, build a tags to testname association
                        for tag in tags:
                            if not self.update_cache["tags"].get(tag):
                                self.update_cache["tags"][tag] = {}

                            self.update_cache["tags"][tag][name] = description

                if executor:
                    self.update_cache["unique_executors"].append(executor)

                    if not self.update_cache["executor"].get(executor):
                        self.update_cache["executor"][executor] = {}

                    self.update_cache["executor"][executor][name] = description

        self.update_cache["unique_tags"] = list(set(self.update_cache["unique_tags"]))
        self.update_cache["unique_executors"] = list(
            set(self.update_cache["unique_executors"])
        )
        self._write_buildspec_cache()

    def check_filter_fields(self):
        """This method checks filter fields are valid. The filter fields are specified
        as ``buildtest buildspec find --filter <KEY1>=<VAL1>,<KEY2>=<VAL2>,...
        """

        self.executor_filter = None
        self.tags_filter = None
        self.type_filter = None

        if self.filter:

            filter_error = False
            # check if filter keys are accepted filter fields, if not we raise error
            for key in self.filter.keys():
                if key not in self.filter_fields:
                    print(f"Invalid filter key: {key}")
                    filter_error = True

            # raise error if any filter field is invalid
            if filter_error:
                raise BuildTestError(f"Invalid filter fields format {self.filter}")

            self.executor_filter = self.filter.get("executor")
            self.tags_filter = self.filter.get("tags")
            self.type_filter = self.filter.get("type")

    def check_format_fields(self):
        """This method will check if all format fields are valid. Format fields
        are passed comma separated as --format field1,field2,field3,...
        """

        for field in self.default_format_fields:
            self.table[field] = []

        if self.format:

            format_error = False
            for key in self.format.split(","):
                if key not in self.format_fields:
                    print(f"Invalid format field: {key}")
                    format_error = True

                if format_error:
                    raise BuildTestError(f"Invalid format fields format {self.format}")

            # if --format option specified we setup cache dictionary based on format
            # fields that are added to list
            self.table = {}
            for field in self.format.split(","):
                self.table[field] = []

    def _filter_buildspecs(self, executor, tags, schema_type):
        """This method will return a boolean True/False that determines if
        buildspec test entry is skipped as part of filter process. The filter
        are done based on executor, tags, type field. ``True`` indicates test
        needs to be skipped.

        :param executor:  'executor; field from buildspec recipe
        :type executor: str, required
        :param tags: 'tags' field from buildspec recipe
        :type tags: str or list, required
        :param schema_type: 'type' field from buildspec recipe
        :type schema_type: str, required
        :return: boolean to determine if we need to skip buildspec
        :rtype: bool
        """

        # skip all entries that dont match filtered executor
        if self.executor_filter and self.executor_filter != executor:
            return True

        # if skip all entries that dont match filtered tag. We only search if --filter tag=value is set
        if self.tags_filter:
            # if tags is not set in buildspec cache we default to empty list which and this condition should always be true
            if self.tags_filter not in tags:
                return True

        if self.type_filter and self.type_filter != schema_type:
            return True

        return False

    def find_buildspecs(self):
        """This method will find buildspecs based on cache content. We skip any
        tests based on executor filter, tag filter or type filter and build
        a table of tests that will be printed using print_buildspecs method.
        """

        for buildspecfile in self.cache["buildspecs"].keys():
            for test in self.cache["buildspecs"][buildspecfile].keys():

                test_recipe = self.cache["buildspecs"][buildspecfile][test]
                schema_type = test_recipe.get("type")
                executor = test_recipe.get("executor")
                # if tags not defined in cache we set to empty list for comparison with tag_filter
                tags = test_recipe.get("tags") or []
                description = test_recipe.get("description")

                # filters buildspecs by executor, tags, type field. The return
                # is a boolean, if its True we skip the test
                if self._filter_buildspecs(executor, tags, schema_type):
                    continue

                if self.format:
                    for field in self.table.keys():
                        if field == "type":
                            self.table[field].append(schema_type)

                        elif field == "file":
                            self.table[field].append(buildspecfile)
                        elif field == "name":
                            self.table[field].append(test)
                        # description, tags, executor have matching format fields with buildspec properties
                        else:
                            self.table[field].append(test_recipe.get(field))

                else:
                    self.table["name"].append(test)
                    self.table["type"].append(schema_type)
                    self.table["executor"].append(executor)
                    self.table["tags"].append(tags)
                    self.table["description"].append(description)

    def get_buildspecfiles(self):
        """This method implements ``buildtest buildspec find --buildspec-files``
        which reports all buildspec files in cache.
        """

        table = {"buildspecs": self.cache["buildspecs"].keys()}
        print(tabulate(table, headers=table.keys(), tablefmt="grid"))

    def get_tags(self):
        """This method implements ``buildtest buildspec find --tags`` which
        reports a list of unique tags from all buildspecs in cache file.
        """

        table = {"Tags": self.cache["unique_tags"]}
        print(tabulate(table, headers=table.keys(), tablefmt="grid"))

    def get_executors(self):
        """This method implements ``buildtest buildspec find --list-executors``
        which reports all executors from cache.
        """

        table = {"executors": self.cache["unique_executors"]}

        print(tabulate(table, headers=table.keys(), tablefmt="grid"))

    def print_by_executors(self):
        """This method prints executors by tests and implements
        ``buildtest buildspec find --group-by-executor`` command
        """

        table = {"executor": [], "name": [], "description": []}

        for executor_name in self.cache["executor"].keys():
            for test_name, description in self.cache["executor"][executor_name].items():
                table["executor"].append(executor_name)
                table["name"].append(test_name)
                table["description"].append(description)

        print(tabulate(table, headers=table.keys(), tablefmt="grid"))

    def print_by_tags(self):
        """This method prints tags by tests and implements
        ``buildtest buildspec find --group-by-tags`` command
        """

        table = {"tags": [], "name": [], "description": []}

        for tagname in self.cache["tags"].keys():
            for test_name, description in self.cache["tags"][tagname].items():
                table["tags"].append(tagname)
                table["name"].append(test_name)
                table["description"].append(description)

        print(tabulate(table, headers=table.keys(), tablefmt="grid"))

    def print_buildspecs(self):
        """Print buildspec table"""

        print(tabulate(self.table, headers=self.table.keys(), tablefmt="grid"))

    def print_maintainer(self):
        """This method prints maintainers from buildspec cache file which implements
        ``buildtest buildspec find --maintainers`` command.
        """

        table = {"maintainers": []}

        for maintainer in self.cache["maintainers"].keys():
            table["maintainers"].append(maintainer)

        print(tabulate(table, headers=table.keys(), tablefmt="grid"))

    def print_maintainers_by_buildspecs(self):
        """This method prints maintainers breakdown by buildspecs. This method
        implements ``buildtest buildspec find --maintainers-by-buildspecs
        """

        table = {"maintainers": [], "buildspec": []}
        for maintainer, buildspec in self.cache["maintainers"].items():
            table["maintainers"].append(maintainer)
            table["buildspec"].append(buildspec)

        print(tabulate(table, headers=table.keys(), tablefmt="grid"))

    @staticmethod
    def print_filter_fields():
        """This method prints filter fields available for buildspec cache. This
        method implements command ``buildtest buildspec find --helpfilter``"""

        filter_field_table = [
            ["executor", "Filter by executor name", "STRING"],
            ["tags", "Filter by tag name ", "STRING"],
            ["type", "Filter by schema type ", "STRING"],
        ]

        print(
            tabulate(
                filter_field_table,
                headers=["Field", "Description", "Type"],
                tablefmt="simple",
            )
        )

    @staticmethod
    def print_format_fields():
        """This method prints format fields available for buildspec cache. This
        method implements command ``buildtest buildspec find --helpformat``"""

        format_fields = [
            ["name", "Format by test name"],
            ["tags", "Format by tag name "],
            ["type", "Format by schema type"],
            ["executor", "Format by executor type"],
            ["description", "Format by description"],
            ["file", "Format by file"],
        ]

        print(
            tabulate(
                format_fields,
                headers=["Field", "Description"],
                tablefmt="simple",
            )
        )

    def print_paths(self):
        """This method print buildspec paths, this implements command
        ``buildtest buildspec find --paths``
        """

        for path in self.paths:
            print(path)


def func_buildspec_find(args):
    """Entry point for ``buildtest buildspec find``. This method
    will attempt to read for buildspec cache file (BUILDSPEC_CACHE_FILE)
    if found and print a list of all buildspecs. Otherwise, it will
    find and load all buildspecs and validate them using BuildspecParser class.
    BuildspecParser will raise SystemError or ValidationError if a buildspec
    is invalid which will be added to list of invalid buildspecs. Finally we
    print a list of all valid buildspecs and any invalid buildspecs are
    written to file along with error message.

    :param args: Input argument from command line passed from argparse
    :return: A list of valid buildspecs found in all repositories.
    """

    bp_cache = BuildspecCache(
        rebuild=args.rebuild,
        filterfields=args.filter,
        formatfields=args.format,
        roots=args.root,
    )

    # implements buildtest buildspec find --tags
    if args.tags:
        bp_cache.get_tags()
        return

    # implements buildtest buildspec find --buildspec-files
    if args.buildspec_files:
        bp_cache.get_buildspecfiles()
        return

    if args.paths:
        bp_cache.print_paths()
        return

    # implements buildtest buildspec find --executors
    if args.executors:
        bp_cache.get_executors()
        return

    if args.group_by_executor:
        bp_cache.print_by_executors()
        return

    if args.group_by_tags:
        bp_cache.print_by_tags()
        return

    # implements buildtest buildspec find --maintainers
    if args.maintainers:
        bp_cache.print_maintainer()
        return

    if args.maintainers_by_buildspecs:
        bp_cache.print_maintainers_by_buildspecs()
        return

    # implements buildtest buildspec find --helpfilter
    if args.helpfilter:
        bp_cache.print_filter_fields()
        return

    # implements buildtest buildspec find --helpformat
    if args.helpformat:
        bp_cache.print_format_fields()
        return

    bp_cache.print_buildspecs()
