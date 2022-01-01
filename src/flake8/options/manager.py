"""Option handling and Option management logic."""
import argparse
import enum
import functools
import logging
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Set
from typing import Tuple
from typing import Type
from typing import Union

from flake8 import utils
from flake8.plugins.finder import Plugins

LOG = logging.getLogger(__name__)

# represent a singleton of "not passed arguments".
# an enum is chosen to trick mypy
_ARG = enum.Enum("_ARG", "NO")


_optparse_callable_map: Dict[str, Union[Type[Any], _ARG]] = {
    "int": int,
    "long": int,
    "string": str,
    "float": float,
    "complex": complex,
    "choice": _ARG.NO,
    # optparse allows this but does not document it
    "str": str,
}


class _CallbackAction(argparse.Action):
    """Shim for optparse-style callback actions."""

    def __init__(
        self,
        *args: Any,
        callback: Callable[..., Any],
        callback_args: Sequence[Any] = (),
        callback_kwargs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self._callback = callback
        self._callback_args = callback_args
        self._callback_kwargs = callback_kwargs or {}
        super().__init__(*args, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Optional[Union[Sequence[str], str]],
        option_string: Optional[str] = None,
    ) -> None:
        if not values:
            values = None
        elif isinstance(values, list) and len(values) > 1:
            values = tuple(values)
        self._callback(
            self,
            option_string,
            values,
            parser,
            *self._callback_args,
            **self._callback_kwargs,
        )


def _flake8_normalize(
    value: str,
    *args: str,
    comma_separated_list: bool = False,
    normalize_paths: bool = False,
) -> Union[str, List[str]]:
    ret: Union[str, List[str]] = value
    if comma_separated_list and isinstance(ret, str):
        ret = utils.parse_comma_separated_list(value)

    if normalize_paths:
        if isinstance(ret, str):
            ret = utils.normalize_path(ret, *args)
        else:
            ret = utils.normalize_paths(ret, *args)

    return ret


class Option:
    """Our wrapper around an argparse argument parsers to add features."""

    def __init__(
        self,
        short_option_name: Union[str, _ARG] = _ARG.NO,
        long_option_name: Union[str, _ARG] = _ARG.NO,
        # Options below here are taken from the optparse.Option class
        action: Union[str, Type[argparse.Action], _ARG] = _ARG.NO,
        default: Union[Any, _ARG] = _ARG.NO,
        type: Union[str, Callable[..., Any], _ARG] = _ARG.NO,
        dest: Union[str, _ARG] = _ARG.NO,
        nargs: Union[int, str, _ARG] = _ARG.NO,
        const: Union[Any, _ARG] = _ARG.NO,
        choices: Union[Sequence[Any], _ARG] = _ARG.NO,
        help: Union[str, _ARG] = _ARG.NO,
        metavar: Union[str, _ARG] = _ARG.NO,
        # deprecated optparse-only options
        callback: Union[Callable[..., Any], _ARG] = _ARG.NO,
        callback_args: Union[Sequence[Any], _ARG] = _ARG.NO,
        callback_kwargs: Union[Mapping[str, Any], _ARG] = _ARG.NO,
        # Options below are taken from argparse.ArgumentParser.add_argument
        required: Union[bool, _ARG] = _ARG.NO,
        # Options below here are specific to Flake8
        parse_from_config: bool = False,
        comma_separated_list: bool = False,
        normalize_paths: bool = False,
    ) -> None:
        """Initialize an Option instance.

        The following are all passed directly through to argparse.

        :param str short_option_name:
            The short name of the option (e.g., ``-x``). This will be the
            first argument passed to ``ArgumentParser.add_argument``
        :param str long_option_name:
            The long name of the option (e.g., ``--xtra-long-option``). This
            will be the second argument passed to
            ``ArgumentParser.add_argument``
        :param default:
            Default value of the option.
        :param dest:
            Attribute name to store parsed option value as.
        :param nargs:
            Number of arguments to parse for this option.
        :param const:
            Constant value to store on a common destination. Usually used in
            conjunction with ``action="store_const"``.
        :param iterable choices:
            Possible values for the option.
        :param str help:
            Help text displayed in the usage information.
        :param str metavar:
            Name to use instead of the long option name for help text.
        :param bool required:
            Whether this option is required or not.

        The following options may be passed directly through to :mod:`argparse`
        but may need some massaging.

        :param type:
            A callable to normalize the type (as is the case in
            :mod:`argparse`).  Deprecated: you can also pass through type
            strings such as ``'int'`` which are handled by :mod:`optparse`.
        :param str action:
            Any action allowed by :mod:`argparse`.  Deprecated: this also
            understands the ``action='callback'`` action from :mod:`optparse`.
        :param callable callback:
            Callback used if the action is ``"callback"``.  Deprecated: please
            use ``action=`` instead.
        :param iterable callback_args:
            Additional positional arguments to the callback callable.
            Deprecated: please use ``action=`` instead (probably with
            ``functools.partial``).
        :param dictionary callback_kwargs:
            Keyword arguments to the callback callable. Deprecated: please
            use ``action=`` instead (probably with ``functools.partial``).

        The following parameters are for Flake8's option handling alone.

        :param bool parse_from_config:
            Whether or not this option should be parsed out of config files.
        :param bool comma_separated_list:
            Whether the option is a comma separated list when parsing from a
            config file.
        :param bool normalize_paths:
            Whether the option is expecting a path or list of paths and should
            attempt to normalize the paths to absolute paths.
        """
        if (
            long_option_name is _ARG.NO
            and short_option_name is not _ARG.NO
            and short_option_name.startswith("--")
        ):
            short_option_name, long_option_name = _ARG.NO, short_option_name

        # optparse -> argparse `%default` => `%(default)s`
        if help is not _ARG.NO and "%default" in help:
            LOG.warning(
                "option %s: please update `help=` text to use %%(default)s "
                "instead of %%default -- this will be an error in the future",
                long_option_name,
            )
            help = help.replace("%default", "%(default)s")

        # optparse -> argparse for `callback`
        if action == "callback":
            LOG.warning(
                "option %s: please update from optparse `action='callback'` "
                "to argparse action classes -- this will be an error in the "
                "future",
                long_option_name,
            )
            action = _CallbackAction
            if type is _ARG.NO:
                nargs = 0

        # optparse -> argparse for `type`
        if isinstance(type, str):
            LOG.warning(
                "option %s: please update from optparse string `type=` to "
                "argparse callable `type=` -- this will be an error in the "
                "future",
                long_option_name,
            )
            type = _optparse_callable_map[type]

        # flake8 special type normalization
        if comma_separated_list or normalize_paths:
            type = functools.partial(
                _flake8_normalize,
                comma_separated_list=comma_separated_list,
                normalize_paths=normalize_paths,
            )

        self.short_option_name = short_option_name
        self.long_option_name = long_option_name
        self.option_args = [
            x
            for x in (short_option_name, long_option_name)
            if x is not _ARG.NO
        ]
        self.action = action
        self.default = default
        self.type = type
        self.dest = dest
        self.nargs = nargs
        self.const = const
        self.choices = choices
        self.callback = callback
        self.callback_args = callback_args
        self.callback_kwargs = callback_kwargs
        self.help = help
        self.metavar = metavar
        self.required = required
        self.option_kwargs: Dict[str, Union[Any, _ARG]] = {
            "action": self.action,
            "default": self.default,
            "type": self.type,
            "dest": self.dest,
            "nargs": self.nargs,
            "const": self.const,
            "choices": self.choices,
            "callback": self.callback,
            "callback_args": self.callback_args,
            "callback_kwargs": self.callback_kwargs,
            "help": self.help,
            "metavar": self.metavar,
            "required": self.required,
        }

        # Set our custom attributes
        self.parse_from_config = parse_from_config
        self.comma_separated_list = comma_separated_list
        self.normalize_paths = normalize_paths

        self.config_name: Optional[str] = None
        if parse_from_config:
            if long_option_name is _ARG.NO:
                raise ValueError(
                    "When specifying parse_from_config=True, "
                    "a long_option_name must also be specified."
                )
            self.config_name = long_option_name[2:].replace("-", "_")

        self._opt = None

    @property
    def filtered_option_kwargs(self) -> Dict[str, Any]:
        """Return any actually-specified arguments."""
        return {
            k: v for k, v in self.option_kwargs.items() if v is not _ARG.NO
        }

    def __repr__(self) -> str:  # noqa: D105
        parts = []
        for arg in self.option_args:
            parts.append(arg)
        for k, v in self.filtered_option_kwargs.items():
            parts.append(f"{k}={v!r}")
        return f"Option({', '.join(parts)})"

    def normalize(self, value: Any, *normalize_args: str) -> Any:
        """Normalize the value based on the option configuration."""
        if self.comma_separated_list and isinstance(value, str):
            value = utils.parse_comma_separated_list(value)

        if self.normalize_paths:
            if isinstance(value, list):
                value = utils.normalize_paths(value, *normalize_args)
            else:
                value = utils.normalize_path(value, *normalize_args)

        return value

    def to_argparse(self) -> Tuple[List[str], Dict[str, Any]]:
        """Convert a Flake8 Option to argparse ``add_argument`` arguments."""
        return self.option_args, self.filtered_option_kwargs


class OptionManager:
    """Manage Options and OptionParser while adding post-processing."""

    def __init__(
        self,
        *,
        version: str,
        plugin_versions: str,
        parents: List[argparse.ArgumentParser],
    ) -> None:
        """Initialize an instance of an OptionManager.

        :param str prog:
            Name of the actual program (e.g., flake8).
        :param str version:
            Version string for the program.
        :param str usage:
            Basic usage string used by the OptionParser.
        :param argparse.ArgumentParser parents:
            A list of ArgumentParser objects whose arguments should also be
            included.
        """
        self.parser = argparse.ArgumentParser(
            prog="flake8",
            usage="%(prog)s [options] file file ...",
            parents=parents,
            epilog=f"Installed plugins: {plugin_versions}",
        )
        self.parser.add_argument(
            "--version",
            action="version",
            version=(
                f"{version} ({plugin_versions}) "
                f"{utils.get_python_version()}"
            ),
        )
        self.parser.add_argument("filenames", nargs="*", metavar="filename")

        self.config_options_dict: Dict[str, Option] = {}
        self.options: List[Option] = []
        self.extended_default_ignore: Set[str] = set()
        self.extended_default_select: Set[str] = set()

        self._current_group: Optional[argparse._ArgumentGroup] = None

    # TODO: maybe make this a free function to reduce api surface area
    def register_plugins(self, plugins: Plugins) -> None:
        """Register the plugin options (if needed)."""
        groups: Dict[str, argparse._ArgumentGroup] = {}

        def _set_group(name: str) -> None:
            try:
                self._current_group = groups[name]
            except KeyError:
                group = self.parser.add_argument_group(name)
                self._current_group = groups[name] = group

        for loaded in plugins.all_plugins():
            add_options = getattr(loaded.obj, "add_options", None)
            if add_options:
                _set_group(loaded.plugin.package)
                add_options(self)

            self.extend_default_select(loaded.entry_name)

        # isn't strictly necessary, but seems cleaner
        self._current_group = None

    def add_option(self, *args: Any, **kwargs: Any) -> None:
        """Create and register a new option.

        See parameters for :class:`~flake8.options.manager.Option` for
        acceptable arguments to this method.

        .. note::

            ``short_option_name`` and ``long_option_name`` may be specified
            positionally as they are with argparse normally.
        """
        option = Option(*args, **kwargs)
        option_args, option_kwargs = option.to_argparse()
        if self._current_group is not None:
            self._current_group.add_argument(*option_args, **option_kwargs)
        else:
            self.parser.add_argument(*option_args, **option_kwargs)
        self.options.append(option)
        if option.parse_from_config:
            name = option.config_name
            assert name is not None
            self.config_options_dict[name] = option
            self.config_options_dict[name.replace("_", "-")] = option
        LOG.debug('Registered option "%s".', option)

    def remove_from_default_ignore(self, error_codes: Sequence[str]) -> None:
        """Remove specified error codes from the default ignore list.

        :param list error_codes:
            List of strings that are the error/warning codes to attempt to
            remove from the extended default ignore list.
        """
        LOG.debug("Removing %r from the default ignore list", error_codes)
        for error_code in error_codes:
            try:
                self.extended_default_ignore.remove(error_code)
            except (ValueError, KeyError):
                LOG.debug(
                    "Attempted to remove %s from default ignore"
                    " but it was not a member of the list.",
                    error_code,
                )

    def extend_default_ignore(self, error_codes: Sequence[str]) -> None:
        """Extend the default ignore list with the error codes provided.

        :param list error_codes:
            List of strings that are the error/warning codes with which to
            extend the default ignore list.
        """
        LOG.debug("Extending default ignore list with %r", error_codes)
        self.extended_default_ignore.update(error_codes)

    def extend_default_select(self, error_codes: Sequence[str]) -> None:
        """Extend the default select list with the error codes provided.

        :param list error_codes:
            List of strings that are the error/warning codes with which
            to extend the default select list.
        """
        LOG.debug("Extending default select list with %r", error_codes)
        self.extended_default_select.update(error_codes)

    def parse_args(
        self,
        args: Optional[Sequence[str]] = None,
        values: Optional[argparse.Namespace] = None,
    ) -> argparse.Namespace:
        """Proxy to calling the OptionParser's parse_args method."""
        if values:
            self.parser.set_defaults(**vars(values))
        return self.parser.parse_args(args)
