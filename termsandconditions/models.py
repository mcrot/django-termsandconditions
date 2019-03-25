"""Django Models for TermsAndConditions App"""

# pylint: disable=C1001,E0202,W0613
from collections import OrderedDict

from django.db import models
from django.conf import settings
from django import VERSION as DJANGO_VERSION

if DJANGO_VERSION <= (2, 0, 0):
    from django.core.urlresolvers import reverse
else:
    from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.models import Q

import logging

LOGGER = logging.getLogger(name='termsandconditions')

DEFAULT_TERMS_SLUG = getattr(settings, 'DEFAULT_TERMS_SLUG', 'site-terms')
TERMS_CACHE_SECONDS = getattr(settings, 'TERMS_CACHE_SECONDS', 30)
TERMS_EXCLUDE_USERS_WITH_PERM = getattr(settings, 'TERMS_EXCLUDE_USERS_WITH_PERM', None)

SKIP_OPTIONAL_CACHE_KEY_SUFFIX = "_skip_optional"
SKIP_SEEN_CACHE_KEY_SUFFIX = "_skip_seen"

class UserTermsAndConditions(models.Model):
    """Holds mapping between TermsAndConditions and Users

    An entry means:

    - terms have been presented to the user
    - for mandatory terms: terms have been accepted (date_accepted must be set)
    - for optional terms: terms are either accepted (date_accepted is set)
                          or not accepted yet ((date_accepted is None)

    Accepted terms have an non-null value for date_accepted.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="userterms", on_delete=models.CASCADE)
    terms = models.ForeignKey("TermsAndConditions", related_name="userterms", on_delete=models.CASCADE)
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name=_('IP Address'))
    date_accepted = models.DateTimeField(null=True, blank=True, default=timezone.now, verbose_name=_('Date Accepted'))

    class Meta:
        """Model Meta Information"""
        get_latest_by = 'date_accepted'
        verbose_name = _('User Terms and Conditions')
        verbose_name_plural = _('User Terms and Conditions')
        unique_together = ('user', 'terms',)

    def __str__(self):  # pragma: nocover
        return "{0}:{1}-{2:.2f}".format(self.user.get_username(), self.terms.slug, self.terms.version_number)

    def clean(self, *args, **kwargs):
        """Ensure these are no mandatory terms with date_accepted==None.

        This is used e.g. when saving in the Admin site.
        """
        if (self.date_accepted is None) and not self.terms.optional:
            raise ValidationError("Mapping between users and mandatory terms must have 'date_accepted' set.")

        super().clean(*args, **kwargs)

class TermsAndConditions(models.Model):
    """Holds Versions of TermsAndConditions
    Active one for a given slug is: date_active is not Null and is latest not in future
    Optional terms: Requested if active, but their acceptance is not mandatory for using the site
    """
    slug = models.SlugField(default=DEFAULT_TERMS_SLUG)
    name = models.TextField(max_length=255)
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, through=UserTermsAndConditions, blank=True)
    version_number = models.DecimalField(default=1.0, decimal_places=2, max_digits=6)
    text = models.TextField(null=True, blank=True)
    info = models.TextField(
        null=True, blank=True, help_text=_("Provide users with some info about what's changed and why")
    )
    date_active = models.DateTimeField(blank=True, null=True, help_text=_("Leave Null To Never Make Active"))
    date_created = models.DateTimeField(blank=True, auto_now_add=True)
    optional = models.BooleanField(default=False)

    class Meta:
        """Model Meta Information"""
        ordering = ['-date_active', ]
        get_latest_by = 'date_active'
        verbose_name = 'Terms and Conditions'
        verbose_name_plural = 'Terms and Conditions'

    def __str__(self):  # pragma: nocover
        return "{0}-{1:.2f}".format(self.slug, self.version_number)

    def get_absolute_url(self):
        return reverse(
            'tc_view_specific_version_page',
            args=[self.slug, self.version_number])  # pylint: disable=E1101

    @staticmethod
    def get_active(slug=DEFAULT_TERMS_SLUG):
        """Finds the latest of a particular terms and conditions"""

        active_terms = cache.get('tandc.active_terms_' + slug)
        if active_terms is None:
            try:
                active_terms = TermsAndConditions.objects.filter(
                    date_active__isnull=False,
                    date_active__lte=timezone.now(),
                    slug=slug).latest('date_active')
                cache.set('tandc.active_terms_' + slug, active_terms, TERMS_CACHE_SECONDS)
            except TermsAndConditions.DoesNotExist:  # pragma: nocover
                LOGGER.error("Requested Terms and Conditions that Have Not Been Created.")
                return None

        return active_terms

    @staticmethod
    def get_active_terms_ids():
        """Returns a list of the IDs of of all terms and conditions"""

        active_terms_ids = cache.get('tandc.active_terms_ids')
        if active_terms_ids is None:
            active_terms_dict = {}
            active_terms_ids = []

            active_terms_set = TermsAndConditions.objects.filter(date_active__isnull=False, date_active__lte=timezone.now()).order_by('date_active')
            for active_terms in active_terms_set:
                active_terms_dict[active_terms.slug] = active_terms.id

            active_terms_dict = OrderedDict(sorted(active_terms_dict.items(), key=lambda t: t[0]))

            for terms in active_terms_dict:
                active_terms_ids.append(active_terms_dict[terms])

            cache.set('tandc.active_terms_ids', active_terms_ids, TERMS_CACHE_SECONDS)

        return active_terms_ids

    @staticmethod
    def get_active_terms_list():
        """Returns all the latest active terms and conditions"""

        active_terms_list = cache.get('tandc.active_terms_list')
        if active_terms_list is None:
            active_terms_list = TermsAndConditions.objects.filter(id__in=TermsAndConditions.get_active_terms_ids()).order_by('slug')
            cache.set('tandc.active_terms_list', active_terms_list, TERMS_CACHE_SECONDS)

        return active_terms_list

    @staticmethod
    def get_active_terms_not_agreed_to(user, skip_optional=False):
        """Checks to see if a specified user has agreed to all the latest terms and conditions

        If you skip optional terms, they won't be returned here even if they're active.

        However only those optional terms will be returned which have not been shown yet.
        Optional terms which have a database entry for a user are always excluded from the result.
        """

        if TERMS_EXCLUDE_USERS_WITH_PERM is not None:
            if user.has_perm(TERMS_EXCLUDE_USERS_WITH_PERM) and not user.is_superuser:
                # Django's has_perm() returns True if is_superuser, we don't want that
                return []

        cache_key_suffix = SKIP_OPTIONAL_CACHE_KEY_SUFFIX if skip_optional else ""

        not_agreed_terms = cache.get('tandc.not_agreed_terms_' + user.get_username() + cache_key_suffix)
        if not_agreed_terms is None:
            try:
                LOGGER.debug("Not Agreed Terms")
                # exclude all terms which have been seen and accepted
                not_agreed_terms = TermsAndConditions.get_active_terms_list().exclude(
                    userterms__in=UserTermsAndConditions.objects.filter(user=user, date_accepted__isnull=False))

                # optionally also exclude the optional terms which have been seen but not accepted
                # Always exclude optional terms already seen.
                optional_cond = Q(optional=True)
                if not skip_optional:
                    # always skip optionals already seen
                    optional_cond &= Q(userterms__in=UserTermsAndConditions.objects.filter(user=user))

                not_agreed_terms = not_agreed_terms.exclude(optional_cond)

                #
                # We want to have all optional terms at the end
                #
                not_agreed_terms = not_agreed_terms.order_by('optional', 'slug')
                if not_agreed_terms and not_agreed_terms.first().optional:
                    # Workaround: depending on the database backend, True comes first when sorting for boolean field
                    not_agreed_terms = not_agreed_terms.order_by('-optional', 'slug')

                cache.set('tandc.not_agreed_terms_' + user.get_username() + cache_key_suffix,
                          not_agreed_terms, TERMS_CACHE_SECONDS)
            except (TypeError, UserTermsAndConditions.DoesNotExist) as exc:
                return []

        return not_agreed_terms
