import logging
import inspect
import astroid
import operator
import re
from inspect import Parameter
from ._docstring_parser import DocstringParser, TypeHintParser
from ._base_node import NodeEntityBase, get_qualified_name
from ._argtype import ArgType


KW_ARG_NAME = "**kwargs"
VALIDATION_REQUIRED_DUNDER = ["__init__",]
KWARG_NOT_REQUIRED_METHODS = ["close",]
TYPEHINT_NOT_REQUIRED_METHODS = ["close",]
REGEX_ITEM_PAGED = "~[\w.]*\.([\w]*)\s?[\[\(][\w]*[\]\)]"
PAGED_TYPES = ["ItemPaged", "AsyncItemPaged",]


def is_kwarg_mandatory(func_name):
    return not func_name.startswith("_") and func_name not in KWARG_NOT_REQUIRED_METHODS


def is_typehint_mandatory(func_name):
    return not func_name.startswith("_") and func_name not in TYPEHINT_NOT_REQUIRED_METHODS


class FunctionNode(NodeEntityBase):
    """Function node class represents parsed function signature.
    Keyword args will be parsed and added to signature if docstring is available.
    :param str: namespace
    :param NodeEntityBase: parent_node
    :param function: obj
    :param bool: is_module_level
    """

    def __init__(self, namespace, parent_node, obj, is_module_level=False):
        super().__init__(namespace, parent_node, obj)
        self.annotations = []
        self.args = []
        self.return_type = None
        self.namespace_id = self.generate_id()
        # Set name space level ID as full name
        # Name space ID will be later updated for async methods
        self.full_name = self.namespace_id
        self.is_class_method = False
        self.is_module_level = is_module_level
        # Some of the methods wont be listed in API review
        # For e.g. ABC methods if class implements all ABC methods
        self.hidden = False
        self._inspect()


    def _inspect(self):
        logging.debug("Processing function {0}".format(self.name))
        code = inspect.getsource(self.obj).strip()
        # We cannot do "startswith" check here due to annotations or decorators present for functions
        self.is_async = "async def" in code
        self.def_key = "async def" if self.is_async else "def"
        # Update namespace ID to reflect async status. Otherwise ID will conflict between sync and async methods
        if self.is_async:
            self.namespace_id += ":async"

        # Find decorators and any annotations
        try:
            node = astroid.extract_node(inspect.getsource(self.obj))
            if node.decorators:
                self.annotations = [
                    "@{}".format(x.name)
                    for x in node.decorators.nodes
                    if hasattr(x, "name")
                ]
        except:
            # todo Update exception details in error
            error_message = "Error in parsing decorators for function {}".format(
                self.name
            )
            self.errors.append(error_message)
            logging.error(error_message)

        self.is_class_method = "@classmethod" in self.annotations
        self._parse_function()


    def _parse_function(self):
        """
        Find positional and keyword arguements, type and default value and return type of method
        Parsing logic will follow below order to identify these information
        1. Identify args, types, default and ret type using inspect
        2. Parse type annotations if inspect doesn't have complete info
        3. Parse docstring to find keyword arguements
        4. Parse type hints
        """
        # Add cls as first arg for class methods in API review tool
        if "@classmethod" in self.annotations:
            self.args.append(ArgType("cls"))

        # Find signature to find positional args and return type
        sig = inspect.signature(self.obj)
        params = sig.parameters
        # Add all keyword only args here temporarily until docstring is parsed
        # This is to handle the scenario is keyword arg typehint (py3 style is present in signature itself)
        self.kw_args = []
        for argname in params:
            arg = ArgType(argname, get_qualified_name(params[argname].annotation), "", self)
            # set default value if available
            if params[argname].default != Parameter.empty:
                arg.default = str(params[argname].default)
            # Store handle to kwarg object to replace it later
            if params[argname].kind == Parameter.VAR_KEYWORD:
                arg.argname = KW_ARG_NAME

            if params[argname].kind == Parameter.KEYWORD_ONLY:
                self.kw_args.append(arg)
            else:
                self.args.append(arg)

        if sig.return_annotation:
            self.return_type = get_qualified_name(sig.return_annotation)

        # parse docstring
        self._parse_docstring()
        # parse type hints
        self._parse_typehint()
        self._copy_kw_args()

        if not self.return_type and is_typehint_mandatory(self.name):
            self.errors.append("Return type is missing in both typehint and docstring")
        # Validate return type
        self._validate_pageable_api()


    def _copy_kw_args(self):
        # Copy kw only args from signature and docstring
        kwargs = [x for x in self.args if x.argname == KW_ARG_NAME]
        # add keyword args
        if self.kw_args:
            # Add separator to differentiate pos_arg and keyword args
            self.args.append(ArgType("*"))
            self.kw_args.sort(key=operator.attrgetter("argname"))
            # Add parsed keyword args to function signature after updating current function node as parent in arg
            for arg in self.kw_args:
                arg.set_function_node(self)
                self.args.append(arg)

            # remove arg with name "**kwarg and add at the end"
            if kwargs:
                kw_arg = kwargs[0]
                self.args.remove(kw_arg)
                self.args.append(kw_arg)

        # API must have **kwargs for non async methods. Flag it as an error if it is missing for public API
        if not kwargs and is_kwarg_mandatory(self.name):
            self.errors.append("Keyword arg (**kwargs) is missing in method {}".format(self.name))


    def _parse_docstring(self):
        # Parse docstring to get list of keyword args, type and default value for both positional and
        # kw args and return type( if not already found in signature)
        docstring = ""
        if hasattr(self.obj, "__doc__"):
            docstring = getattr(self.obj, "__doc__")
        # Refer docstring at class if this is constructor and docstring is missing for __init__
        if (
            not docstring
            and self.name == "__init__"
            and hasattr(self.parent_node.obj, "__doc__")
        ):
            docstring = getattr(self.parent_node.obj, "__doc__")

        if docstring:
            #  Parse doc string to find missing types, kwargs and return type
            parsed_docstring = DocstringParser(docstring)
            parsed_docstring.parse()
            # Set return type if not already set
            if not self.return_type and parsed_docstring.ret_type:
                logging.debug(
                    "Setting return type from docstring for method {}".format(self.name)
                )
                self.return_type = parsed_docstring.ret_type

            # Update arg type from docstring if available and if argtype is missing from signatrue parsing
            arg_type_dict = dict(
                [(x.argname, x.argtype) for x in parsed_docstring.pos_args]
            )
            for pos_arg in self.args:
                pos_arg.argtype = arg_type_dict.get(
                    pos_arg.argname, pos_arg.argtype
                )

            self.kw_args.extend(parsed_docstring.kw_args)            


    def _parse_typehint(self):

        # Skip parsing typehint if typehint is not expected for e.g dunder or async methods
        if not is_typehint_mandatory(self.name) or self.is_async:
            return

        # Parse type hint to get return type and types for positional args
        typehint_parser = TypeHintParser(self.obj)
        # Find return type from type hint if return type is not already set
        type_hint_ret_type = typehint_parser.find_return_type()
        # Type hint must be present for all APIs. Flag it as an error if typehint is missing
        if  not type_hint_ret_type:
            self.errors.append("Typehint is missing for method {}".format(self.name))
            return

        if not self.return_type:
            self.return_type = type_hint_ret_type
        else:
            # Verify return type is same in docstring and typehint if typehint is available
            short_return_type = self.return_type.split(".")[-1]
            long_ret_type = self.return_type
            if long_ret_type != type_hint_ret_type and short_return_type != type_hint_ret_type:
                error_message = "Return type in type hint is not matching return type in docstring"
                self.errors.append(error_message)


    def _generate_signature_token(self, apiview):
        apiview.add_punctuation("(")
        args_count = len(self.args)
        use_multi_line = args_count > 2
        # Show args in individual line if method has more than 4 args and use two tabs to properly aign them
        if use_multi_line:
            apiview.begin_group()
            apiview.begin_group()

        # Generate token for each arg
        for index in range(args_count):
            # Add new line if args are listed in new line
            if use_multi_line:
                apiview.add_new_line()
                apiview.add_whitespace()

            self.args[index].generate_tokens(
                apiview, self.namespace_id, use_multi_line
            )
            # Add punctuation between types except for last one
            if index < args_count - 1:
                apiview.add_punctuation(",", False, True)

        if use_multi_line:
            apiview.add_new_line()
            apiview.end_group()
            apiview.add_whitespace()
            apiview.add_punctuation(")")
            apiview.end_group()
        else:
            apiview.add_punctuation(")")


    def generate_tokens(self, apiview):
        """Generates token for function signature
        :param ApiView: apiview
        """
        logging.info("Processing method {0} in class {1}".format(self.name, self.parent_node.namespace_id))
        # Add tokens for annotations
        for annot in self.annotations:
            apiview.add_whitespace()
            apiview.add_keyword(annot)
            apiview.add_new_line()

        apiview.add_whitespace()
        apiview.add_line_marker(self.namespace_id)
        if self.is_async:
            apiview.add_keyword("async", False, True)

        apiview.add_keyword("def", False, True)
        # Show fully qualified name for module level function and short name for instance functions
        apiview.add_text(
            self.namespace_id, self.full_name if self.is_module_level else self.name
        )
        # Add parameters
        self._generate_signature_token(apiview)
        if self.return_type:
            apiview.add_punctuation("->", True, True)
            # Add line marker id if signature is displayed in multi lines
            if len(self.args) > 2:
                line_id = "{}.returntype".format(self.namespace_id)
                apiview.add_line_marker(line_id)
            apiview.add_type(self.return_type)

        if self.errors:
            for e in self.errors:
                apiview.add_diagnostic(e, self.namespace_id)


    def add_error(self, error_msg):
        # Hide all diagnostics for now for dunder methods
        # These are well known protocol implementation
        if not self.name.startswith("_") or self.name in VALIDATION_REQUIRED_DUNDER:
            self.errors.append(error_msg)


    def _validate_pageable_api(self):
        # If api name starts with "list" and if annotated with "@distributed_trace"
        # then this method should return ItemPaged or AsyncItemPaged
        if self.return_type and self.name.startswith("list") and  "@distributed_trace" in self.annotations:
            tokens = re.search(REGEX_ITEM_PAGED, self.return_type)
            if tokens:
                ret_short_type = tokens.groups()[-1]
                if ret_short_type in PAGED_TYPES:
                    logging.debug("list API returns valid paged return type")
                    return
            error_msg = "list API {0} should return ItemPaged or AsyncItemPaged".format(self.name)
            logging.error(error_msg)
            self.add_error(error_msg)                
        

    def print_errors(self):
        if self.errors:
            print("  method: {}".format(self.name))
            for e in self.errors:
                print("      {}".format(e))
