import logging
import inspect
import astroid

from ._base_node import NodeEntityBase


class EnumNode(NodeEntityBase):
    """Enum node represents any Enum value
    """

    def __init__(self, namespace, parent_node, obj):
        super().__init__(namespace, parent_node, obj)
        self.name = obj.name
        self.value = obj.value
        self.namespace_id = self.generate_id()

    def generate_tokens(self, apiview):
        """Generates token for the node and it's children recursively and add it to apiview
        :param ApiView: apiview
        """
        apiview.add_line_marker(self.namespace_id)
        apiview.add_text(self.namespace_id, self.name)
        apiview.add_space()
        apiview.add_punctuation("=")
        apiview.add_space()
        if isinstance(self.value, str):
            apiview.add_stringliteral(self.value)
        else:
            apiview.add_literal(str(self.value))

    def print_errors(self):
        if self.errors:
            print("enum: {}".format(self.name))
            for e in self.errors:
                print("    {}".format(e))