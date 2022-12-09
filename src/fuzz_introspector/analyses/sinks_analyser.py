# Copyright 2022 Fuzz Introspector Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Analysis plugin for introspection sinks of interest"""

import logging

from typing import (
    List,
    Tuple,
    Dict
)

from fuzz_introspector import (
    analysis,
    cfg_load,
    html_helpers,
    utils
)

from fuzz_introspector.datatypes import (
    project_profile,
    fuzzer_profile,
    function_profile
)

logger = logging.getLogger(name=__name__)

# Common sink functions / methods for different language implementation
SINK_FUNCTION = {
    'c-cpp': [
        ('', 'system'),
        ('', 'execl'),
        ('', 'execve'),
        ('', 'wordexp'),
        ('', 'popen'),
        ('', 'fdopen')
    ],
    'python': [
        ('', 'exec'),
        ('', 'eval'),
        ('subprocess', 'call'),
        ('subprocess', 'run'),
        ('subprocess', 'Popen'),
        ('subprocess', 'check_output'),
        ('os', 'system'),
        ('os', 'popen'),
        ('os', 'spawnlpe'),
        ('os', 'spawnve'),
        ('os', 'execl'),
        ('os', 'execve'),
        ('asyncio', 'create_subprocess_shell'),
        ('asyncio', 'create_subprocess_exec'),
        ('asyncio', 'run'),
        ('asyncio', 'sleep'),
        ('logging.config', 'listen'),
        ('code.InteractiveInterpreter', 'runsource'),
        ('code.InteractiveInterpreter', 'runcode'),
        ('code.InteractiveInterpreter', 'write'),
        ('code.InteractiveConsole', 'push'),
        ('code.InteractiveConsole', 'interact'),
        ('code.InteractiveConsole', 'raw_input'),
        ('code', 'interact'),
        ('code', 'compile_command')
    ],
    'jvm': [
        ('java.lang.Runtime', 'exec'),
        ('javax.xml.xpath.XPath', 'compile'),
        ('javax.xml.xpath.XPath', 'evaluate'),
        ('java.lang.Thread', 'sleep'),
        ('java.lang.Thread', 'run'),
        ('java.lang.Runnable', 'run'),
        ('java.util.concurrent.Executor', 'execute'),
        ('java.util.concurrent.Callable', 'call'),
        ('java.lang.System', 'console'),
        ('java.lang.System', 'load'),
        ('java.lang.System', 'loadLibrary'),
        ('java.lang.System', 'apLibraryName'),
        ('java.lang.System', 'runFinalization'),
        ('java.lang.System', 'setErr'),
        ('java.lang.System', 'setIn'),
        ('java.lang.System', 'setOut'),
        ('java.lang.System', 'setProperties'),
        ('java.lang.System', 'setProperty'),
        ('java.lang.System', 'setSecurityManager'),
        ('java.lang.ProcessBuilder', 'directory'),
        ('java.lang.ProcessBuilder', 'inheritIO'),
        ('java.lang.ProcessBuilder', 'command'),
        ('java.lang.ProcessBuilder', 'edirectError'),
        ('java.lang.ProcessBuilder', 'redirectErrorStream'),
        ('java.lang.ProcessBuilder', 'redirectInput'),
        ('java.lang.ProcessBuilder', 'redirectOutput'),
        ('java.lang.ProcessBuilder', 'start')
    ]
}


class Analysis(analysis.AnalysisInterface):
    """This Analysis aims to analyse and generate html report content table
    to show all occurence of possible sink functions / methods existed in the
    target project and if those functions / methods are statically reached or
    dynamically covered by any of the fuzzers. If not, it also provides the
    closet callable entry points to those sink functions / methods for fuzzer
    developers to improve their fuzzers to statically reached and dynamically
    covered those sensitive sink fnctions / method in aid to discover possible
    code / command injection through though fuzzing on sink functions / methods..
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def get_name():
        return "SinkCoverageAnalyser"

    def _get_source_file(self, callsite) -> str:
        """This function aims to dig up the callsitecalltree of a function
        call and get its source file path.
        """
        src_file = callsite.src_function_source_file
        if not src_file:
            parent = callsite.parent_calltree_callsite
            if parent:
                src_file = parent.dst_function_source_file
                src_file = src_file if src_file else ""

        return src_file

    def _get_parent_func_name(self, callsite) -> str:
        """This function aims to dig up the callsitecalltree of a function
        call and get its parent function name.
        """
        func_file = callsite.src_function_source_file
        if not func_file:
            parent = callsite.parent_calltree_callsite
            if parent:
                func_file = parent.dst_function_name
                func_file = func_file if func_file else ""

        return func_file

    def retrieve_data_list(
        self,
        proj_profile: project_profile.MergedProjectProfile,
        profiles: List[fuzzer_profile.FuzzerProfile]
    ) -> Tuple[List[cfg_load.CalltreeCallsite], List[function_profile.FunctionProfile]]:
        """
        Retrieve and return full list of call sites and functions
        from all fuzzers profile for this project
        """
        callsite_list = []
        function_list = []
        function_name_list: List[str] = []

        for (key, function) in proj_profile.all_functions.items():
            if key not in function_name_list:
                function_list.append(function)
                function_name_list.append(function.function_name)

        for profile in profiles:
            if profile.function_call_depths is not None:
                callsite_list.extend(cfg_load.extract_all_callsites(profile.function_call_depths))
            for (key, function) in profile.all_class_functions.items():
                if key not in function_name_list:
                    function_list.append(function)
                    function_name_list.append(function.function_name)

        return (callsite_list, function_list)

    def map_function_callsite(
        self,
        functions: List[function_profile.FunctionProfile],
        callsites: List[cfg_load.CalltreeCallsite]
    ) -> Dict[str, List[str]]:
        """
        This function aims to dig up the callsite for each function
        and store the mapped source location and line number list as
        a formatted string list.
        """
        callsite_dict: Dict[str, List[str]] = dict()

        # Initialize callsite_dict with target function names
        for function in functions:
            callsite_dict[function.function_name] = []

        # Map callsite for all target functions
        for callsite in callsites:
            func_name = callsite.dst_function_name
            if func_name in callsite_dict.keys():
                callsite_dict[func_name].append(
                    "%s#%s:%s" % (
                        self._get_source_file(callsite),
                        self._get_parent_func_name(callsite),
                        callsite.src_linenumber
                    )
                )

        # Sort and make unique for callsites of each function
        for (key, value) in callsite_dict.items():
            callsite_dict[key] = list(set(value))

        return callsite_dict

    def retrieve_reachable_functions(
        self,
        functions: List[function_profile.FunctionProfile],
        function_callsites: Dict[str, List[str]]
    ) -> List[str]:
        """
        This function aims to dig up the source of all reachable
        functions and store the fromatted string of its source
        location and line number in the list.
        """
        function_list = []

        # Loop and find if matched callsite string for the function does exists
        for function in functions:
            for (func_name, callsite_str) in function.callsite.items():
                if callsite_str in function_callsites[func_name]:
                    function_list.extend(callsite_str)

        # Sort and make unique for the reachable function list
        function_list = list(set(function_list))

        return function_list

    def filter_function_list(
        self,
        functions: List[function_profile.FunctionProfile],
        target_lang: str
    ) -> List[function_profile.FunctionProfile]:
        """
        This function aim to filter out target list of functions
        which are considered as sinks for separate langauge which
        is the major analysing target for this SinkAnalyser.
        """
        function_list = []

        # Loop through the all function list for a project
        for fd in functions:
            # Separate handling for different target language
            if target_lang == "c-cpp":
                func_name = utils.demangle_cpp_func(fd.function_name)
                package = ''
            elif target_lang == "python":
                func_name = fd.function_name
                package = fd.function_source_file
            elif target_lang == "jvm":
                func_name = fd.function_name.split('(')[0]
                if "." in func_name:
                    package, func_name = func_name.rsplit('.', 1)
                else:
                    package = 'default'
            else:
                continue

            # Add the function profile to the result list if it matches one of the target
            if (package, func_name) in SINK_FUNCTION[target_lang]:
                function_list.append(fd)

        return function_list

    def analysis_func(
        self,
        toc_list: List[Tuple[str, str, int]],
        tables: List[str],
        proj_profile: project_profile.MergedProjectProfile,
        profiles: List[fuzzer_profile.FuzzerProfile],
        basefolder: str,
        coverage_url: str,
        conclusions: List[html_helpers.HTMLConclusion]
    ) -> str:
        """
        Show all used sensitive sink functions / methods in the project and display
        if any fuzzers statically or dynamically reached them. If not, display closest
        entry point to reach them.
        1) Loop through the all function list of the project and see if any of the sink
           functions exists.
        2) Shows if each of those third party function call location is statically
           reachable
        3) Analyse and show closet entry point suggestions for fuzzers developer to
           statically reached those functions / methods
        4) Analyse the fuzzer report to determine if each of those statically reachable
           sink functions / methods has been dynamically coveed by any of the fuzzers
        5) Provide additional entry point to increase the chance of dynamically covering
           those sink functions / methods.
        """
        logger.info(f" - Running analysis {Analysis.get_name()}")

        # Get full function /  callsite list for all fuzzer's profiles
        callsite_list, function_list = self.retrieve_data_list(proj_profile, profiles)

        # Map callsites to each function
        function_callsite_dict = self.map_function_callsite(function_list, callsite_list)

        # Discover reachable function calls
        reachable_function_list = self.retrieve_reachable_functions(
            function_list,
            function_callsite_dict
        )

        html_string = ""
        html_string += "<div class=\"report-box\">"

        html_string += html_helpers.html_add_header_with_link(
            "Function call coverage",
            1,
            toc_list
        )

        # Table with all function calls for each files
        html_string += "<div class=\"collapsible\">"
        html_string += (
            "<p>"
            "This section shows a chosen list of functions / methods "
            "calls and their relative coverage information. By static "
            "analysis of the target project code, all of these function "
            "call and their caller information, including the source file "
            "or class and line number that initiate the call are captured. "
            "The caller source code file or class and the line number are "
            "shown in column 2 while column 1 is the function name of that "
            "selected functions or methods call. Each occurrent of the target "
            "function call will occuply a separate row. Column 3 of each row "
            "indicate if the target function calls is statically unreachable."
            "Column 4 lists all fuzzers (or no fuzzers at all) that have "
            "covered that particular system call in  dynamic fuzzing. Those "
            "functions with low to  no reachability and dynamic hit count indicate "
            "missed fuzzing logic to fuzz and track for possible code injection sinks."
            "</p>"
        )

        html_string += html_helpers.html_add_header_with_link(
            "Function in each files in report",
            2,
            toc_list
        )

        # Third party function calls table
        tables.append(f"myTable{len(tables)}")
        html_string += html_helpers.html_create_table_head(
            tables[-1],
            [
                ("Target sink", ""),
                ("Callsite location",
                 "Source file, line number and parent function of this function call. "
                 "Based on static analysis."),
                ("Reached by fuzzer",
                 "Is this code reachable by any functions? "
                 "Based on static analysis."),
                ("Covered by Fuzzers",
                 "The specific list of fuzzers that cover this function call. "
                 "Based on dynamic analysis.")
            ]
        )

        for fd in self.filter_function_list(function_list, profiles[0].target_lang):
            # Loop through the list of calledlocation for this function
            for called_location in function_callsite_dict[fd.function_name]:
                # Determine if this called location is covered by any fuzzers
                fuzzer_hit = False
                coverage = proj_profile.runtime_coverage
                for parent_func in fd.incoming_references:
                    try:
                        lineno = int(called_location.split(":")[1])
                    except ValueError:
                        continue
                    if coverage.is_func_lineno_hit(parent_func, lineno):
                        fuzzer_hit = True
                        break
                list_of_fuzzer_covered = fd.reached_by_fuzzers if fuzzer_hit else [""]

                html_string += html_helpers.html_table_add_row([
                    f"{fd.function_name}",
                    f"{called_location}",
                    f"{called_location in reachable_function_list}",
                    f"{str(list_of_fuzzer_covered)}"
                ])
        html_string += "</table>"

        html_string += "</div>"  # .collapsible
        html_string += "</div>"  # report-box

        logger.info(f" - Finish running analysis {Analysis.get_name()}")
        return html_string
