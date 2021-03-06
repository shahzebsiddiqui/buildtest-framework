import json
import os
import sys
from tabulate import tabulate
from buildtest.defaults import BUILD_REPORT
from buildtest.exceptions import BuildTestError
from buildtest.utils.file import is_file, create_dir, resolve_path


def is_int(val):
    num = val
    try:
        num = int(num)
    except ValueError:
        return False
    return True


class Report:
    # all format fields available for --helpformat
    format_fields = [
        "buildspec",
        "name",
        "id",
        "full_id",
        "testroot",
        "testpath",
        "command",
        "outfile",
        "errfile",
        "schemafile",
        "executor",
        "tags",
        "starttime",
        "endtime",
        "runtime",
        "state",
        "returncode",
    ]
    filter_fields = ["buildspec", "name", "executor", "state", "tags", "returncode"]

    # default table format fields
    display_table = {
        "name": [],
        "id": [],
        "state": [],
        "returncode": [],
        "starttime": [],
        "endtime": [],
        "runtime": [],
        "tags": [],
        "buildspec": [],
    }

    def __init__(self, filter_args, format_args):
        self.filter = filter_args
        self.format = format_args
        self.report = self.load()
        self._check_filter_fields()
        self._check_format_fields()
        self.filter_buildspecs_from_report()

        self.process_report()

    def _check_filter_fields(self):
        # check if filter arguments (--filter) are valid fields
        if self.filter:

            raiseError = False
            # check if filter keys are accepted filter fields, if not we raise error
            for key in self.filter.keys():
                if key not in self.filter_fields:
                    print(f"Invalid filter key: {key}")
                    raiseError = True

                if key == "returncode" and not is_int(self.filter[key]):
                    raise BuildTestError(
                        f"Invalid returncode:{self.filter[key]} must be an integer"
                    )

            # raise error if any filter field is invalid
            if raiseError:
                sys.exit(1)

    def _check_format_fields(self):

        self.display_format_fields = self.display_table.keys()

        # if buildtest report --format specified split field by "," and validate each
        # format field and reassign display_table
        if self.format:
            self.display_format_fields = self.format.split(",")
            # check all input format fields are valid fields
            for field in self.display_format_fields:
                if field not in self.format_fields:
                    sys.exit(f"Invalid format field: {field}")

            # reassign display_table to format fields
            self.display_table = {}

            for field in self.display_format_fields:
                self.display_table[field] = []

    def load(self):
        """This method is responsible for loading report file. If file not found
           or report is empty dictionary we raise an error. The report file
           is loaded using ``json.loads`` and return value is a dictionary containing
           entire report of all tests.
        """

        # raise error if BUILD_REPORT not found
        if not is_file(BUILD_REPORT):
            sys.exit(f"Unable to fetch report no such file found: {BUILD_REPORT}")

        report = None
        with open(BUILD_REPORT, "r") as fd:
            report = json.loads(fd.read())

        # if report is None or issue with how json.load returns content of file we
        # raise error
        if not report:
            sys.exit(
                f"Fail to process {BUILD_REPORT} please check if file is valid json"
                f"or remove file"
            )
        return report

    def filter_buildspecs_from_report(self):
        # filter_buildspecs = self.report.keys()
        # print (self.filter, filter_buildspecs)
        # This section filters the buildspec, if its invalid file or not found in cache
        # we raise error, otherwise we set filter_buildspecs to the filter argument 'buildspec'

        # by default all keys from report are buildspec files to process
        self.filtered_buildspecs = self.report.keys()

        # if --filter option not specified we return from method
        if not self.filter:
            return

        if self.filter.get("buildspec"):
            # resolve path for buildspec filter key, its possible if file doesn't exist method returns None
            resolved_buildspecs = resolve_path(self.filter["buildspec"])

            # if file doesn't exist we terminate with message
            if not resolved_buildspecs:
                print(
                    f"Invalid File Path for filter field 'buildspec': {self.filter['buildspec']}"
                )
                sys.exit(0)

            # if file not found in cache we exit
            if not resolved_buildspecs in self.report.keys():
                print(f"buildspec file: {resolved_buildspecs} not found in cache")
                sys.exit(0)

            # need to set as a list since we will loop over all tests
            self.filtered_buildspecs = [resolved_buildspecs]

        # ensure 'state' field in filter is either 'PASS' or 'FAIL', if not raise error
        if self.filter.get("state"):
            if self.filter["state"] not in ["PASS", "FAIL"]:
                print(
                    f"filter argument 'state' must be 'PASS' or 'FAIL' got value {self.filter['state']}"
                )
                sys.exit(0)

    def _filter_test_by_names(self, name):

        if not self.filter.get("name"):
            return False

        # skip tests that don't equal filter 'name' field
        if name == self.filter.get("name"):
            return False

        return True

    def _filter_test_by_tags(self, test):

        if self.filter.get("tags") and self.filter.get("tags") not in test.get("tags"):
            return True

        return False

    def _filter_test_by_executor(self, test):

        if self.filter.get("executor") and self.filter.get("executor") != test.get(
            "executor"
        ):
            return True

        return False

    def _filter_test_by_state(self, test):

        if self.filter.get("state") and self.filter.get("state") != test.get("state"):
            return True

        return False

    def _filter_test_by_returncode(self, test):

        if self.filter.get("returncode"):
            if int(self.filter["returncode"]) != test.get("returncode"):
                return True

        return False

    def process_report(self):
        # process all filtered buildspecs and add rows to display_table.
        # filter_buildspec is either all buildspec or a single buildspec if
        # 'buildspec' filter field was set

        for buildspec in self.filtered_buildspecs:

            # process each test in buildspec file
            for name in self.report[buildspec].keys():

                if self.filter:
                    if self._filter_test_by_names(name):
                        continue

                # process all tests for an associated script. There can be multiple
                # test runs for a single test depending on how many tests were run
                for test in self.report[buildspec][name]:

                    if self.filter:
                        # filter by tags, if filter tag not found in test tag list we skip test
                        if self._filter_test_by_tags(test):
                            continue

                        # if 'executor' filter defined, skip test that don't match executor key
                        if self._filter_test_by_executor(test):
                            continue

                        # if state filter defined, skip any tests that don't match test state
                        if self._filter_test_by_state(test):
                            continue

                        # if returncode filter defined, skip any tests that don't match returncode
                        if self._filter_test_by_returncode(test):
                            continue

                    if "buildspec" in self.display_table.keys():
                        self.display_table["buildspec"].append(buildspec)

                    if "name" in self.display_table.keys():
                        self.display_table["name"].append(name)

                    for field in self.display_format_fields:
                        # skip fields buildspec or name since they are accounted above and not part
                        # of test dictionary
                        if field in ["buildspec", "name"]:
                            continue

                        self.display_table[field].append(test[field])

    def print_format_fields(self):
        """Implements command ``buildtest report --helpformat``"""
        format_table = [
            ["buildspec", "Buildspec file"],
            ["name", "Name of test defined in buildspec"],
            ["id", "Unique Build Identifier (abbreviated)"],
            ["full_id", "Full qualified unique build identifier"],
            ["testroot", "Root of test directory"],
            ["testpath", "Path to test"],
            ["command", "Command executed"],
            ["outfile", "Output file"],
            ["errfile", "Error File"],
            ["schemafile", "Schema file used for validation"],
            ["executor", "Executor name"],
            ["tags", "Tag name"],
            ["starttime", "Start Time of test in date format"],
            ["endtime", "End Time for Test in date format"],
            ["runtime", "Total runtime in seconds"],
            ["state", "Test State reported by buildtest (PASS/FAIL)"],
            ["returncode", "Return Code from Test Execution"],
        ]
        print(
            tabulate(format_table, headers=["Fields", "Description"], tablefmt="simple")
        )

    def print_filter_fields(self):
        """Implements command ``buildtest report --helpfilter``"""

        filter_field_table = [
            ["buildspec", "Filter by buildspec file", "FILE"],
            ["name", "Filter by test name", "STRING"],
            ["executor", "Filter by executor name", "STRING"],
            ["state", "Filter by test state ", "PASS/FAIL"],
            ["tags", "Filter tests by tag name ", "STRING"],
            ["returncode", "Filter tests by returncode ", "INT"],
        ]

        print(
            tabulate(
                filter_field_table,
                headers=["Filter Fields", "Description", "Expected Value"],
                tablefmt="simple",
            )
        )

    def print_display_table(self):
        print(
            tabulate(
                self.display_table, headers=self.display_table.keys(), tablefmt="grid"
            )
        )


def func_report(args=None):
    results = Report(args.filter, args.format)
    if args.helpfilter:
        results.print_filter_fields()
        return

    if args.helpformat:
        results.print_format_fields()
        return

    results.print_display_table()


def update_report(valid_builders):
    """This method will update BUILD_REPORT after every test run performed
       by ``buildtest build``. If BUILD_REPORT is not created, we will create
       file and update json file by extracting contents from builder.metadata

       :param valid_builders: builder object that were successful during build and able to execute test
       :type valid_builders: instance of BuilderBase (subclass)
    """

    if not is_file(os.path.dirname(BUILD_REPORT)):
        create_dir(os.path.dirname(BUILD_REPORT))

    # if file exists, read json file otherwise set report to empty dict
    try:
        with open(BUILD_REPORT, "r") as fd:
            report = json.loads(fd.read())
    except OSError:
        report = {}

    for builder in valid_builders:
        buildspec = builder.metadata["buildspec"]
        name = builder.metadata["name"]
        entry = {}

        report[buildspec] = report.get(buildspec) or {}
        report[buildspec][name] = report.get(buildspec, {}).get(name) or []

        # query over attributes found in builder.metadata, we only assign
        # keys that we care obout for reporting
        for item in [
            "id",
            "full_id",
            "testroot",
            "testpath",
            "command",
            "outfile",
            "errfile",
            "schemafile",
            "executor",
        ]:
            entry[item] = builder.metadata[item]

        entry["tags"] = ""
        # convert tags to string if defined in buildspec
        if builder.metadata["tags"]:
            if isinstance(builder.metadata["tags"], list):
                entry["tags"] = " ".join(builder.metadata["tags"])
            else:
                entry["tags"] = builder.metadata["tags"]

        # query over result attributes, we only assign some keys of interest
        for item in ["starttime", "endtime", "runtime", "state", "returncode"]:
            entry[item] = builder.metadata["result"][item]

        entry["job"] = builder.metadata.get("job") or None
        report[buildspec][name].append(entry)

    with open(BUILD_REPORT, "w") as fd:
        json.dump(report, fd, indent=2)
