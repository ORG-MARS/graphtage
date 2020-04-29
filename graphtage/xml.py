import html
import os
import sys
import xml.etree.ElementTree as ET
from typing import Any, Collection, Dict, Optional, Iterator, Sequence, Union

from .bounds import Range
from .edits import AbstractCompoundEdit, Insert, Match, Remove
from .formatter import Formatter
from .graphtage import ContainerNode, DictNode, Filetype, FixedKeyDictNode, KeyValuePairNode, ListNode, StringNode
from .printer import Back, Fore, Printer
from .sequences import SequenceFormatter
from .tree import Edit, EditedTreeNode, TreeNode


class XMLElementEdit(AbstractCompoundEdit):
    def __init__(self, from_node: 'XMLElement', to_node: 'XMLElement'):
        self.tag_edit: Edit = from_node.tag.edits(to_node.tag)
        self.attrib_edit: Edit = from_node.attrib.edits(to_node.attrib)
        if from_node.text is not None and to_node.text is not None:
            self.text_edit: Optional[Edit] = from_node.text.edits(to_node.text)
        elif from_node.text is None and to_node.text is not None:
            self.text_edit: Optional[Edit] = Insert(to_insert=to_node.text, insert_into=from_node)
        elif to_node.text is None and from_node.text is not None:
            self.text_edit: Optional[Edit] = Remove(to_remove=from_node.text, remove_from=from_node)
        else:
            self.text_edit: Optional[Edit] = None
        self.child_edit: Edit = from_node._children.edits(to_node._children)
        super().__init__(
            from_node=from_node,
            to_node=to_node
        )

    def print(self, formatter: Formatter, printer: Printer):
        formatter.get_formatter(self.from_node)(printer, self.from_node, self)

    def bounds(self) -> Range:
        if self.text_edit is not None:
            text_bounds = self.text_edit.bounds()
        else:
            text_bounds = Range(0, 0)
        return text_bounds + self.tag_edit.bounds() + self.attrib_edit.bounds() + self.child_edit.bounds()

    def edits(self) -> Iterator[Edit]:
        yield self.tag_edit
        yield self.attrib_edit
        if self.text_edit is not None:
            yield self.text_edit
        yield self.child_edit

    def is_complete(self) -> bool:
        return self.tag_edit.is_complete() and (self.text_edit is None or self.text_edit.is_complete()) \
            and self.attrib_edit.is_complete() and self.child_edit.is_complete()

    def tighten_bounds(self) -> bool:
        if self.tag_edit.tighten_bounds():
            return True
        elif self.text_edit is not None and self.text_edit.tighten_bounds():
            return True
        elif self.attrib_edit.tighten_bounds():
            return True
        elif self.child_edit.tighten_bounds():
            return True
        else:
            return False


class XMLElement(ContainerNode):
    def __init__(
            self,
            tag: StringNode,
            attrib: Optional[Dict[StringNode, StringNode]] = None,
            text: Optional[StringNode] = None,
            children: Sequence['XMLElement'] = (),
            allow_key_edits: bool = True
    ):
        self.tag: StringNode = tag
        tag.quoted = False
        if attrib is None:
            attrib = {}
        if allow_key_edits:
            self.attrib: DictNode = DictNode(attrib)
        else:
            self.attrib = FixedKeyDictNode(attrib)
        if isinstance(self, EditedTreeNode):
            self.attrib = self.attrib.make_edited()
        self.attrib.start_symbol = ''
        self.attrib.end_symbol = ''
        self.attrib.delimiter = ''
        self.attrib.delimiter_callback = lambda p: p.newline()
        for key, _ in self.attrib.items():
            key.quoted = False
        self.text: Optional[StringNode] = text
        if self.text is not None:
            self.text.quoted = False
        self._children: ListNode = ListNode(children)
        if isinstance(self, EditedTreeNode):
            self._children = self._children.make_edited()
        self.attrib.start_symbol = ''
        self.attrib.end_symbol = ''
        self.attrib.delimiter_callback = lambda p: p.newline()

    def children(self) -> Collection['TreeNode']:
        ret = (self.tag, self.attrib)
        if self.text is not None:
            return ret + (self.text, self._children)
        else:
            return ret + (self._children,)

    def __repr__(self):
        return f"{self.__class__.__name__}(tag={self.tag!r}, attrib={self.attrib!r}, text={self.text!r}, children={self._children!r})"

    def __str__(self):
        return f"<{self.tag.object}{''.join(' ' + key.object + '=' + value.object for key, value in self.attrib.items())} ... />"

    def edits(self, node) -> Edit:
        if self == node:
            return Match(self, node, 0)
        else:
            return XMLElementEdit(self, node)

    def calculate_total_size(self) -> int:
        if self.text is None:
            t_size = 0
        else:
            t_size = self.text.total_size
        return t_size + self.tag.total_size + self.attrib.total_size + self._children.total_size

    def _print_text(self, printer: Printer):
        if self.text is None:
            return
        if '\n' not in self.text.object and not self._children._children:
            printer.write(html.escape(self.text.object))
            return
        with printer.indent():
            for section in self.text.object.split('\n'):
                printer.newline()
                printer.write(html.escape(section))

    def print(self, printer: Printer, edit: Optional[XMLElementEdit] = None):
        XMLFormatter.DEFAULT_INSTANCE.print(printer=printer, node=self, with_edits=True)
        return
        printer.write('<')
        self.tag.print(printer)
        for key, value in self.attrib.items():
            printer.write(' ')
            key.print(printer)
            printer.write('=')
            value.print(printer)
        if self.children.children or (self.text is not None and '\n' in self.text.object):
            printer.write('>')
            self._print_text(printer)
            for child in self.children.children:
                with printer.indent():
                    printer.newline()
                    child.print(printer)
            printer.newline()
            printer.write('</')
            self.tag.print(printer)
            printer.write('>')
        elif self.text is not None:
            printer.write('>')
            self._print_text(printer)
            printer.write('</')
            self.tag.print(printer)
            printer.write('>')
        else:
            printer.write(' />')

    def init_args(self) -> Dict[str, Any]:
        return {
            'tag': self.tag,
            'attrib': {kvp.key: kvp.value for kvp in self.attrib},
            'text': self.text,
            'children': tuple(self._children.__iter__())
        }

    def make_edited(self) -> Union[EditedTreeNode, 'XMLElement']:
        if self.text is None:
            et = None
        else:
            et = self.text.make_edited()
        return EditedXMLElement(
            tag=self.tag.make_edited(),
            attrib={
                kvp.key: kvp.value for kvp in self.attrib
            },
            text=et,
            children=[c for c in self._children]
        )

    def __eq__(self, other):
        if not isinstance(other, XMLElement):
            return False
        return other.tag == self.tag and other.attrib == self.attrib \
               and other.text == self.text and other._children == self._children


class EditedXMLElement(EditedTreeNode, XMLElement):
    def __init__(self, *args, **kwargs):
        EditedTreeNode.__init__(self)
        XMLElement.__init__(self, *args, **kwargs)

    def print(self, printer: Printer):
        xml_edit = None
        for edit in self.edit_list:
            if isinstance(edit, XMLElementEdit):
                xml_edit = xml_edit
        if self.removed:
            with printer.strike():
                with printer.color(Fore.WHITE).background(Back.RED).bright() as p:
                    XMLElement.print(self, p, xml_edit)
        else:
            XMLElement.print(self, printer, xml_edit)


def build_tree(path_or_element_tree: Union[str, ET.Element, ET.ElementTree], allow_key_edits=True) -> XMLElement:
    if isinstance(path_or_element_tree, ET.Element):
        root: ET.Element = path_or_element_tree
    else:
        if isinstance(path_or_element_tree, str):
            tree: ET.ElementTree = ET.parse(path_or_element_tree)
        else:
            tree: ET.ElementTree = path_or_element_tree
        root: ET.Element = tree.getroot()
    if root.text:
        text = StringNode(root.text)
    else:
        text = None
    return XMLElement(
        tag=StringNode(root.tag),
        attrib={
            StringNode(k): StringNode(v) for k, v in root.attrib.items()
        },
        text=text,
        children=[build_tree(child, allow_key_edits=allow_key_edits) for child in root],
        allow_key_edits=allow_key_edits
    )


class XMLChildFormatter(SequenceFormatter):
    is_partial = True

    def __init__(self):
        super().__init__('', '', '', lambda p: p.newline())

    def print_ListNode(self, *args, **kwargs):
        super().print_SequenceNode(*args, **kwargs)


class XMLElementAttribFormatter(SequenceFormatter):
    is_partial = True

    def __init__(self):
        super().__init__('', '', '')

    def item_newline(self, printer: Printer, is_first: bool = False, is_last: bool = False):
        pass

    def print_MultiSetNode(self, *args, **kwargs):
        self.print_SequenceNode(*args, **kwargs)

    def print_FixedKeyDictNode(self, *args, **kwargs):
        self.print_SequenceNode(*args, **kwargs)

    def print_KeyValuePairNode(self, printer: Printer, node: KeyValuePairNode):
        printer.write(' ')
        self.print(printer, node.key)
        printer.write('=')
        self.print(printer, node.value)


class XMLFormatter(Formatter):
    sub_format_types = [XMLChildFormatter, XMLElementAttribFormatter]

    @staticmethod
    def _print_text(element: XMLElement, printer: Printer):
        if element.text is None:
            return
        if '\n' not in element.text.object and not element._children._children:
            printer.write(html.escape(element.text.object))
            return
        with printer.indent():
            for section in element.text.object.split('\n'):
                printer.newline()
                printer.write(html.escape(section))

    def print_XMLElement(self, printer: Printer, node: XMLElement, edit: Optional[XMLElementEdit] = None):
        if edit is None:
            edit = XMLElementEdit(node, node)
        printer.write('<')
        edit.tag_edit.print(self, printer)
        #self.print(printer, node.tag)
        if node.attrib:
            #self.print(printer, node.attrib)
            edit.attrib_edit.print(self, printer)
        if node._children._children or (node.text is not None and '\n' in node.text.object):
            printer.write('>')
            self._print_text(node, printer)
            #self.print(printer, node.children)
            edit.child_edit.print(self, printer)
            printer.write('</')
            #self.print(printer, node.tag)
            edit.tag_edit.print(self, printer)
            printer.write('>')
        elif node.text is not None:
            printer.write('>')
            self._print_text(node, printer)
            printer.write('</')
            #self.print(printer, node.tag)
            edit.tag_edit.print(self, printer)
            printer.write('>')
        else:
            printer.write(' />')


class XML(Filetype):
    def __init__(self):
        super().__init__(
            'xml',
            'application/xml',
            'text/xml'
        )

    def build_tree(self, path: str, allow_key_edits: bool = True) -> TreeNode:
        return build_tree(path, allow_key_edits=allow_key_edits)

    def build_tree_handling_errors(self, path: str, allow_key_edits: bool = True) -> TreeNode:
        try:
            return self.build_tree(path=path, allow_key_edits=allow_key_edits)
        except ET.ParseError as pe:
            sys.stderr.write(f'Error parsing {os.path.basename(path)}: {pe.msg}\n\n')
            sys.exit(1)

    def get_default_formatter(self) -> XMLFormatter:
        return XMLFormatter.DEFAULT_INSTANCE


class HTML(XML):
    def __init__(self):
        Filetype.__init__(
            self,
            'html',
            'text/html',
            'application/xhtml+xml'
        )
