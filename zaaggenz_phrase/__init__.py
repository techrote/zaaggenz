"""Predictable phrase-role windows above source-preserving note construction."""
from .model import PhraseRoleError, PhraseRolePlan, VERSION, ROLES
from .expand import RoleExpansion, expand_role_plan
from .presets import template_1234_5555
from .integration import RoleRenderBundle, plan_to_timeline, compile_role_recipe

__all__ = ['PhraseRoleError', 'PhraseRolePlan', 'VERSION', 'ROLES', 'RoleExpansion',
           'expand_role_plan', 'template_1234_5555', 'RoleRenderBundle',
           'plan_to_timeline', 'compile_role_recipe']
