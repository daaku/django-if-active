from django.utils.encoding import smart_str
from django.core.urlresolvers import get_callable, RegexURLResolver, get_resolver
from django.template import Node, NodeList, TextNode, TemplateSyntaxError, Library, resolve_variable
from django.conf import settings

register = Library()

def do_ifactive(parser, token):
    """
    Defines a conditional block tag, "ifactive" that switches based on whether the active request
    is being handled by a particular view (with optional args and kwargs).

    Has the form:

    {% ifactive request path.to.view %}
        [Block to render if path.to.view is the active view]
    {% else %}
        [Block to render if path.to.view is not the active view]
    {% endifactive %}

    'request' is a context variable expression which resolves to the HttpRequest object for the current
    request. (Additionally, the ActiveViewMiddleware must be installed for this to work.)

    'path.to.view' can be a string with a python import path (which must be mentioned in the urlconf),
    or a name of a urlpattern (i.e., same as the argument to the {% url %} tag).

    You can also pass arguments or keyword arguments in the same form as accepted by the {% url %} tag,
    e.g.:

    {% ifactive request path.to.view var1="bar",var2=var.prop %}...{% endifactive %}

    or:

    {% ifactive request path.to.view "bar",var.prop %}...{% endifactive %}

    The else block is optional.
    """

    end_tag = 'endifactive'

    active_nodes = parser.parse((end_tag,'else'))
    end_token = parser.next_token()
    if end_token.contents == 'else':
        inactive_nodes = parser.parse((end_tag,))
        parser.delete_first_token()
    else:
        inactive_nodes = None

    tag_args = token.contents.split(' ')
    if len(tag_args) < 3:
        raise TemplateSyntaxError("'%s' takes at least two arguments"
                                  " (context variable with the request, and path to a view)" % tag_args[0])

    request_var = tag_args[1]
    view_name = tag_args[2]
    args, kwargs = _parse_url_args(parser, tag_args[3:])

    return ActiveNode(request_var, view_name, args, kwargs, active_nodes, inactive_nodes)

register.tag('ifactive', do_ifactive)

class ActiveNode(Node):

    def __init__(self, request_var, view_name, args, kwargs, active_nodes, inactive_nodes=None):
        self.request_var = request_var
        self.view_name = view_name
        self.args = args
        self.kwargs = kwargs
        self.active_nodes = active_nodes
        self.inactive_nodes = inactive_nodes

    def render(self, context):

        request = resolve_variable(self.request_var, context)

        view, default_args = _get_view_and_default_args(self.view_name)

        if getattr(request, '_view_func', None) is view:

            resolved_args = [arg.resolve(context) for arg in self.args]
            if request._view_args == resolved_args:

                resolved_kwargs = dict([(k, v.resolve(context)) for k, v in self.kwargs.items()])
                resolved_kwargs.update(default_args)

                if request._view_kwargs == resolved_kwargs:
                    return self.active_nodes.render(context)

        if self.inactive_nodes is not None:
            return self.inactive_nodes.render(context)
        else:
            return ''

def _get_patterns_map(resolver, default_args=None):
    """
    Recursively generates a map of
    (pattern name or path to view function) -> (view function, default args)
    """

    patterns_map = {}

    if default_args is None:
        default_args = {}

    for pattern in resolver.url_patterns:

        pattern_args = default_args.copy()

        if isinstance(pattern, RegexURLResolver):
            pattern_args.update(pattern.default_kwargs)
            patterns_map.update(_get_patterns_map(pattern, pattern_args))
        else:
            pattern_args.update(pattern.default_args)

            if pattern.name is not None:
                patterns_map[pattern.name] = (pattern.callback, pattern_args)

            # HACK: Accessing private attribute of RegexURLPattern
            callback_str = getattr(pattern, '_callback_str', None)
            if callback_str is not None:
                patterns_map[pattern._callback_str] = (pattern.callback, pattern_args)

    return patterns_map

_view_name_cache = None

def _get_view_and_default_args(view_name):
    """
    Given view_name (a path to a view or a name of a urlpattern,
    returns the view function and a dict containing any default kwargs
    that are specified in the urlconf for that view.
    """

    global _view_name_cache

    if _view_name_cache is None:
        _view_name_cache = _get_patterns_map(get_resolver(None))

    try:
        return _view_name_cache[view_name]
    except KeyError:
        raise KeyError("%s does not match any urlpatterns" % view_name)

def _parse_url_args(parser, bits):
    """
    Parses URL parameters in the same way as the {% url %} tag.
    """

    args = []
    kwargs = {}

    for bit in bits:
        for arg in bit.split(","):
            if '=' in arg:
                k, v = arg.split('=', 1)
                k = k.strip()
                kwargs[smart_str(k,'ascii')] = parser.compile_filter(v)
            elif arg:
                args.append(parser.compile_filter(arg))

    return args, kwargs

def do_activeif(parser, token):
    "e.g. <a {% activeif page1 %} href='{% url page1 %}'>Page 1</a>"
    tag_args = token.contents.split(' ')
    view_name = tag_args[1]
    args, kwargs = _parse_url_args(parser, tag_args[2:])
    return ActiveNode('request', view_name, args, kwargs, NodeList(TextNode('class="active"')))
register.tag('activeif', do_activeif)
