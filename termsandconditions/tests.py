"""Unit Tests for the termsandconditions module"""

# pylint: disable=R0904, C0103
from importlib import import_module
import logging

from django.core import mail
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.conf import settings
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User, ContentType, Permission
from django.template import Context, Template

from .models import TermsAndConditions, UserTermsAndConditions, DEFAULT_TERMS_SLUG
from .pipeline import user_accept_terms
from .templatetags.terms_tags import show_terms_if_not_agreed


LOGGER = logging.getLogger(name='termsandconditions')


class TermsAndConditionsTests(TestCase):
    """Tests Terms and Conditions Module"""

    def setUp(self):
        """Setup for each test"""
        LOGGER.debug('Test Setup')

        self.su = User.objects.create_superuser('su', 'su@example.com', 'superstrong')
        self.user1 = User.objects.create_user('user1', 'user1@user1.com', 'user1password')
        self.user2 = User.objects.create_user('user2', 'user2@user2.com', 'user2password')
        self.user3 = User.objects.create_user('user3', 'user3@user3.com', 'user3password')
        self.terms1 = TermsAndConditions.objects.create(id=1, slug="site-terms", name="Site Terms",
                                                        text="Site Terms and Conditions 1", version_number=1.0,
                                                        date_active="2012-01-01")
        self.terms2 = TermsAndConditions.objects.create(id=2, slug="site-terms", name="Site Terms",
                                                        text="Site Terms and Conditions 2", version_number=2.0,
                                                        date_active="2012-01-05")
        self.terms3 = TermsAndConditions.objects.create(id=3, slug="contrib-terms", name="Contributor Terms",
                                                        text="Contributor Terms and Conditions 1.5", version_number=1.5,
                                                        date_active="2012-01-01")
        self.terms4 = TermsAndConditions.objects.create(id=4, slug="contrib-terms", name="Contributor Terms",
                                                        text="Contributor Terms and Conditions 2", version_number=2.0,
                                                        date_active="2100-01-01")
        self.terms5 = TermsAndConditions.objects.create(id=5, slug="optional-terms", name="Optional Terms",
                                                        text="Optional Terms and Conditions 1.6", version_number=1.6,
                                                        date_active="2012-02-01", optional=True)
        self.terms6 = TermsAndConditions.objects.create(id=6, slug="optional-terms", name="Optional Terms",
                                                        text="Optional Terms and Conditions 2", version_number=2.0,
                                                        date_active="2100-02-01", optional=True)

        # give user3 permission to skip T&Cs
        content_type = ContentType.objects.get_for_model(type(self.user3))
        self.skip_perm = Permission.objects.create(content_type=content_type, name='Can skip T&Cs', codename='can_skip_t&c')
        self.user3.user_permissions.add(self.skip_perm)


    def tearDown(self):
        """Teardown for each test"""
        LOGGER.debug('Test TearDown')
        User.objects.all().delete()
        TermsAndConditions.objects.all().delete()
        UserTermsAndConditions.objects.all().delete()

    def test_social_redirect(self):
        """Test the agreed_to_terms redirect from social pipeline"""
        LOGGER.debug("Test the social pipeline")
        response = user_accept_terms('backend', self.user1, '123')
        self.assertIsInstance(response, HttpResponseRedirect)

        # Accept the mandatory terms, mark optional terms as seen, and try again
        UserTermsAndConditions.objects.create(user=self.user1, terms=self.terms2)
        UserTermsAndConditions.objects.create(user=self.user1, terms=self.terms3)
        UserTermsAndConditions.objects.create(user=self.user1, terms=self.terms5, date_accepted=None) # optional
        response = user_accept_terms('backend', self.user1, '123')
        self.assertIsInstance(response, dict)

    def test_get_active_terms_list(self):
        """Test get list of active T&Cs"""
        active_list = TermsAndConditions.get_active_terms_list()
        self.assertEqual(3, len(active_list))
        self.assertQuerysetEqual(active_list, [repr(self.terms3), repr(self.terms5), repr(self.terms2)])

    def test_get_active_terms_not_agreed_to_only_mandatory(self):
        """Test get mandatory T&Cs not agreed to"""
        active_list = TermsAndConditions.get_active_terms_not_agreed_to(self.user1, skip_optional=True)
        self.assertEqual(2, len(active_list))
        self.assertQuerysetEqual(active_list, [repr(self.terms3), repr(self.terms2)])

    def test_get_active_terms_not_agreed_to_including_optional(self):
        """Test get mandatory T&Cs not agreed to"""
        active_list = TermsAndConditions.get_active_terms_not_agreed_to(self.user1, skip_optional=False)
        self.assertEqual(3, len(active_list))
        self.assertQuerysetEqual(active_list, [repr(self.terms3), repr(self.terms2), repr(self.terms5)])

    def test_user_is_excluded(self):
        """Test user3 has perm which excludes them from having to accept T&Cs"""
        active_list = TermsAndConditions.get_active_terms_not_agreed_to(self.user3)
        self.assertEqual([], active_list)

    def test_superuser_is_not_implicitly_excluded(self):
        """Test su should have to accept T&Cs even if they are superuser but don't explicitly have the skip perm"""
        active_list = TermsAndConditions.get_active_terms_not_agreed_to(self.su, skip_optional=True)
        self.assertEqual(2, len(active_list))
        self.assertQuerysetEqual(active_list, [repr(self.terms3), repr(self.terms2)])

    def test_superuser_cannot_skip(self):
        """Test su still has to accept even if they are explicitly given the skip perm"""
        self.su.user_permissions.add(self.skip_perm)
        active_list = TermsAndConditions.get_active_terms_not_agreed_to(self.su, skip_optional=True)
        self.assertEqual(2, len(active_list))
        self.assertQuerysetEqual(active_list, [repr(self.terms3), repr(self.terms2)])

    def test_get_active_terms_ids(self):
        """Test get ids of active T&Cs"""
        active_list = TermsAndConditions.get_active_terms_ids()
        self.assertEqual(3, len(active_list))
        self.assertEqual(active_list, [3, 5, 2])

    def test_terms_and_conditions_models(self):
        """Various tests of the TermsAndConditions Module"""

        # Testing Direct Assignment of Acceptance
        UserTermsAndConditions.objects.create(user=self.user1, terms=self.terms1)
        UserTermsAndConditions.objects.create(user=self.user2, terms=self.terms3)

        self.assertEquals(1.0, self.user1.userterms.get().terms.version_number)
        self.assertEquals(1.5, self.user2.userterms.get().terms.version_number)

        self.assertEquals('user1', self.terms1.users.all()[0].get_username())

        # Testing the get_active static method of TermsAndConditions
        self.assertEquals(2.0, TermsAndConditions.get_active(slug='site-terms').version_number)
        self.assertEquals(1.5, TermsAndConditions.get_active(slug='contrib-terms').version_number)

        # Testing the unicode method of TermsAndConditions
        self.assertEquals('site-terms-2.00', str(TermsAndConditions.get_active(slug='site-terms')))
        self.assertEquals('contrib-terms-1.50', str(TermsAndConditions.get_active(slug='contrib-terms')))

    def test_middleware_redirect(self):
        """Validate that a user is redirected to the terms accept page if they are logged in, and decorator is on method"""

        UserTermsAndConditions.objects.all().delete()

        LOGGER.debug('Test user1 login for middleware')
        login_response = self.client.login(username='user1', password='user1password')
        self.assertTrue(login_response)

        LOGGER.debug('Test /secure/ after login')
        logged_in_response = self.client.get('/secure/', follow=True)
        self.assertRedirects(logged_in_response, '/terms/accept/contrib-terms?returnTo=/secure/')

    def test_terms_required_redirect(self):
        """Validate that a user is redirected to the terms accept page if logged in, and decorator is on method"""

        LOGGER.debug('Test /termsrequired/ pre login')
        not_logged_in_response = self.client.get('/termsrequired/', follow=True)
        self.assertRedirects(not_logged_in_response, '/accounts/login/?next=/termsrequired/')

        LOGGER.debug('Test user1 login')
        login_response = self.client.login(username='user1', password='user1password')
        self.assertTrue(login_response)

        LOGGER.debug('Test /termsrequired/ after login')
        logged_in_response = self.client.get('/termsrequired/', follow=True)
        self.assertRedirects(logged_in_response, '/terms/accept/?returnTo=/termsrequired/')

        LOGGER.debug('Test no redirect for /termsrequired/ after accept')
        accepted_response = self.client.post('/terms/accept/', {'terms': 2, 'returnTo': '/termsrequired/'}, follow=True)
        self.assertContains(accepted_response, "Please Accept")

        LOGGER.debug('Test response after termsrequired accept')
        terms_required_response = self.client.get('/termsrequired/', follow=True)
        self.assertContains(terms_required_response, "Please Accept")

    def test_accept(self):
        """Validate that accepting non-optional terms works"""

        # First mark optional terms as accepted, so we won't be asked here
        UserTermsAndConditions.objects.create(user=self.user1, terms=self.terms5)

        LOGGER.debug('Test user1 login for accept')
        login_response = self.client.login(username='user1', password='user1password')
        self.assertTrue(login_response)

        LOGGER.debug('Test /terms/accept/ get')
        accept_response = self.client.get('/terms/accept/', follow=True)
        self.assertContains(accept_response, "Accept")

        LOGGER.debug('Test /terms/accept/ post')
        chained_terms_response = self.client.post('/terms/accept/', {'terms': 2, 'returnTo': '/secure/'}, follow=True)
        self.assertContains(chained_terms_response, "Contributor")

        LOGGER.debug('Test /terms/accept/contrib-terms/1.5/ get')
        accept_version_response = self.client.get('/terms/accept/contrib-terms/1.5/', follow=True)
        self.assertContains(accept_version_response, "Contributor Terms and Conditions 1.5")

        LOGGER.debug('Test /terms/accept/contrib-terms/3/ post')
        accept_version_post_response = self.client.post('/terms/accept/', {'terms': 3, 'returnTo': '/secure/'}, follow=True)
        self.assertContains(accept_version_post_response, "Secure")

    def _test_optional_common(self):

        # Accept the mandatory terms first
        UserTermsAndConditions.objects.create(user=self.user1, terms=self.terms2)
        UserTermsAndConditions.objects.create(user=self.user1, terms=self.terms3)

        LOGGER.debug('Test user1 login for accept')
        login_response = self.client.login(username='user1', password='user1password')
        self.assertTrue(login_response)

        LOGGER.debug('Test /terms/accept/optional-terms/1.6/ get')
        accept_version_response = self.client.get('/terms/accept/optional-terms/1.6', follow=True)
        self.assertContains(accept_version_response, "Optional Terms and Conditions 1.6")
        self.assertContains(accept_version_response, "Accept")
        self.assertContains(accept_version_response, "Not now")  # it should be possible to proceed without accepting

    def test_accept_optional(self):
        """Validate that accepting optional terms works"""

        self._test_optional_common()

        LOGGER.debug('Test /terms/accept/contrib-terms/5/ post')
        accept_version_post_response = self.client.post('/terms/accept/', {'terms': 5, 'returnTo': '/secure/'},
                                                        follow=True)
        self.assertContains(accept_version_post_response, "Secure")

    def test_not_accept_optional(self):
        """Validate that not accepting optional terms works"""

        self._test_optional_common()

        LOGGER.debug('Test /terms/accept/contrib-terms/5/ post')
        deny_version_post_response = self.client.post('/terms/accept/', {'terms': 5, 'returnTo': '/secure/',
                                                                         'not_now': True},
                                                        follow=True)
        self.assertContains(deny_version_post_response, "Secure")

    def test_first_not_accept_optional_then_accept_later(self):
        """Validate that accepting optional terms works when accepting it later"""

        self._test_optional_common()

        LOGGER.debug('Test /terms/accept/contrib-terms/5/ post')
        deny_version_post_response = self.client.post('/terms/accept/',
                                                      {'terms': 5, 'returnTo': '/secure/', 'not_now': True},
                                                        follow=True)
        self.assertContains(deny_version_post_response, "Secure")

        # now this should be listed (means "seen"), but not accepted in database
        terms = UserTermsAndConditions.objects.get(user=self.user1, terms_id=5)
        self.assertIsNone(terms.date_accepted)

        # now accept
        LOGGER.debug('Test /terms/accept/contrib-terms/5/ post')
        accept_version_post_response = self.client.post('/terms/accept/', {'terms': 5, 'returnTo': '/secure/'},
                                                      follow=True)
        self.assertContains(accept_version_post_response, "Secure")

        # now this should be accepted in database
        terms = UserTermsAndConditions.objects.get(user=self.user1, terms_id=5)
        self.assertIsNotNone(terms.date_accepted)

    def test_accept_store_ip_address(self):
        """Test with IP address storage setting true (default)"""
        self.client.login(username='user1', password='user1password')
        self.client.post('/terms/accept/', {'terms': 2, 'returnTo': '/secure/'}, follow=True)
        user_terms = UserTermsAndConditions.objects.all()[0]
        self.assertEqual(user_terms.user, self.user1)
        self.assertEqual(user_terms.terms, self.terms2)
        self.assertTrue(user_terms.ip_address)

    def test_accept_no_ip_address(self):
        """Test with IP address storage setting false"""
        self.client.login(username='user1', password='user1password')
        with self.settings(TERMS_STORE_IP_ADDRESS=False):
            self.client.post('/terms/accept/', {'terms': 2, 'returnTo': '/secure/'}, follow=True)
            user_terms = UserTermsAndConditions.objects.all()[0]
            self.assertFalse(user_terms.ip_address)

    def test_terms_upgrade(self):
        """Validate a user is prompted to accept terms again when new version comes out"""

        # Already accept some terms or makr as read
        UserTermsAndConditions.objects.create(user=self.user1, terms=self.terms2)
        UserTermsAndConditions.objects.create(user=self.user1, terms=self.terms5, date_accepted=None)

        LOGGER.debug('Test user1 login pre upgrade')
        login_response = self.client.login(username='user1', password='user1password')
        self.assertTrue(login_response)

        LOGGER.debug('Test user1 not redirected after login')
        logged_in_response = self.client.get('/secure/', follow=True)
        self.assertContains(logged_in_response, "Contributor")

        # First, Accept Contributor Terms
        LOGGER.debug('Test /terms/accept/contrib-terms/3/ post')
        self.client.post('/terms/accept/', {'terms': 3, 'returnTo': '/secure/'}, follow=True)

        LOGGER.debug('Test upgrade terms')
        self.terms7 = TermsAndConditions.objects.create(id=7, slug="site-terms", name="Site Terms",
                                                        text="Terms and Conditions2", version_number=2.5,
                                                        date_active="2012-02-05")

        LOGGER.debug('Test user1 is redirected when changing pages')
        post_upgrade_response = self.client.get('/secure/', follow=True)
        self.assertRedirects(post_upgrade_response, '/terms/accept/site-terms?returnTo=/secure/')

        # Then accept site-terms ..
        self.client.post('/terms/accept/', {'terms': 7, 'returnTo': '/secure/'}, follow=True)

        # .. no redirection any more
        before_new_optional_terms_response = self.client.get('/secure/', follow=True)
        self.assertContains(before_new_optional_terms_response, "Secure")

        # With new optional terms there should be a redirect again
        self.terms8 = TermsAndConditions.objects.create(id=8, slug="optional-terms", name="Site Terms",
                                                        text="Optional Terms and Conditions2", version_number=2.5,
                                                        optional=True,
                                                        date_active="2012-02-05")

        LOGGER.debug('Test user1 is redirected when changing pages after optional terms have been upgraded')
        post_upgrade_response = self.client.get('/secure/', follow=True)
        self.assertRedirects(post_upgrade_response, '/terms/accept/optional-terms?returnTo=/secure/')

    def test_no_middleware(self):
        """Test a secure page with the middleware excepting it"""

        UserTermsAndConditions.objects.create(user=self.user1, terms=self.terms2)

        LOGGER.debug('Test user1 login no middleware')
        login_response = self.client.login(username='user1', password='user1password')
        self.assertTrue(login_response)

        LOGGER.debug('Test user1 not redirected after login')
        logged_in_response = self.client.get('/securetoo/', follow=True)
        self.assertContains(logged_in_response, "SECOND")

        LOGGER.debug("Test startswith '/admin' pages not redirecting")
        admin_response = self.client.get('/admin', follow=True)
        self.assertContains(admin_response, "administration")

    def test_terms_view(self):
        """Test Accessing the View Terms and Conditions Functions"""

        LOGGER.debug('Test /terms/')
        root_response = self.client.get('/terms/', follow=True)
        self.assertContains(root_response, 'Terms and Conditions')

        LOGGER.debug('Test /terms/view/site-terms')
        slug_response = self.client.get('/terms/view/site-terms', follow=True)
        self.assertContains(slug_response, 'Terms and Conditions')

        LOGGER.debug('Test /terms/view/site-terms/1.5')
        version_response = self.client.get(self.terms3.get_absolute_url(), follow=True)
        self.assertContains(version_response, 'Terms and Conditions')

    def test_user_pipeline(self):
        """Test the case of a user being partially created via the django-socialauth pipeline"""

        LOGGER.debug('Test /terms/accept/ post for no user')
        no_user_response = self.client.post('/terms/accept/', {'terms': 2}, follow=True)
        self.assertContains(no_user_response, "Home")

        user = {'pk': self.user1.id}
        kwa = {'user': user}
        partial_pipeline = {'kwargs': kwa}

        engine = import_module(settings.SESSION_ENGINE)
        store = engine.SessionStore()
        store.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = store.session_key

        session = self.client.session
        session["partial_pipeline"] = partial_pipeline
        session.save()

        self.assertTrue('partial_pipeline' in self.client.session)

        LOGGER.debug('Test /terms/accept/ post for pipeline user')
        pipeline_response = self.client.post('/terms/accept/', {'terms': 2, 'returnTo': '/anon'}, follow=True)
        self.assertContains(pipeline_response, "Anon")

    def test_email_terms(self):
        """Test emailing terms and conditions"""
        LOGGER.debug('Test /terms/email/')
        email_form_response = self.client.get('/terms/email/', follow=True)
        self.assertContains(email_form_response, 'Email')

        LOGGER.debug('Test /terms/email/ post, expecting email fail')
        email_send_response = self.client.post('/terms/email/',
                                               {'email_address': 'foo@foo.com', 'email_subject': 'Terms Email',
                                                'terms': 2, 'returnTo': '/'}, follow=True)
        self.assertEqual(len(mail.outbox), 1)  # Check that there is one email in the test outbox
        self.assertContains(email_send_response, 'Sent')

        LOGGER.debug('Test /terms/email/ post, expecting email fail')
        email_fail_response = self.client.post('/terms/email/', {'email_address': 'INVALID EMAIL ADDRESS',
                                                                 'email_subject': 'Terms Email', 'terms': 2,
                                                                 'returnTo': '/'}, follow=True)
        self.assertContains(email_fail_response, 'Invalid')


class TermsAndConditionsTemplateTagsTestCase(TestCase):
    """Tests Tags for T&C"""

    def setUp(self):
        """Setup for each test"""
        self.user1 = User.objects.create_user(
            'user1', 'user1@user1.com', 'user1password')
        self.template_string_1 = (
            '{% load terms_tags %}'
            '{% show_terms_if_not_agreed %}'
        )
        self.template_string_2 = (
            '{% load terms_tags %}'
            '{% show_terms_if_not_agreed slug="specific-terms" %}'
        )
        self.template_string_3 = (
            '{% load terms_tags %}'
            '{% include terms.text|as_template %}'
        )

        self.terms1 = TermsAndConditions.objects.create(id=1, slug="site-terms", name="Site Terms",
                                                        text="Site Terms and Conditions 1", version_number=1.0,
                                                        date_active="2012-01-01")
        self.terms2 = TermsAndConditions.objects.create(id=2, slug="optional-terms", name="Optional Terms",
                                                        text="Optional Terms and Conditions 1", version_number=1.0,
                                                        date_active="2012-02-01", optional=True)
        cache.clear()

    def _make_context(self, url):
        """Build Up Context - Used in many tests"""
        context = dict()
        context['request'] = RequestFactory()
        context['request'].user = self.user1
        context['request'].META = {'PATH_INFO': url}
        return context

    def render_template(self, string, context=None):
        """a helper method to render simplistic test templates"""
        request = RequestFactory().get('/test')
        request.user = self.user1
        request.context = context or {}
        return Template(string).render(Context({'request': request}))

    def test_show_terms_if_not_agreed_to_mandatory(self):
        """test if show_terms_if_not_agreed template tag renders html code for mandatory terms"""
        LOGGER.debug('Test template tag not showing terms if not agreed to')
        rendered = self.render_template(self.template_string_1)
        terms = TermsAndConditions.get_active()
        self.assertIn(terms.slug, rendered)

    def test_not_show_terms_if_agreed_to_mandatory(self):
        """test if show_terms_if_not_agreed template tag does not load if user agreed terms"""
        LOGGER.debug('Test template tag not showing terms once agreed to')
        terms = TermsAndConditions.get_active()
        UserTermsAndConditions.objects.create(terms=terms, user=self.user1) # seen and accpeted
        rendered = self.render_template(self.template_string_1)
        self.assertNotIn(terms.slug, rendered)

    def test_show_terms_if_not_agreed_to_optional_not_seen_yet(self):
        """test if show_terms_if_not_agreed template tag renders html code for optional terms not having been seen"""
        LOGGER.debug('Test template tag showing optional terms if not agreed to and not seen yet')
        rendered = self.render_template(self.template_string_1)
        terms = TermsAndConditions.get_active('optional-terms')
        self.assertIn(terms.slug, rendered)

    def test_not_show_terms_if_not_agreed_to_optional_already_seen(self):
        """test if show_terms_if_not_agreed template tag does not load if user has seen optional terms but didn't agree"""
        LOGGER.debug('Test template tag not showing optional terms not agreed to but already seen')
        terms = TermsAndConditions.get_active('optional-terms')
        UserTermsAndConditions.objects.create(terms=terms, user=self.user1, date_accepted=None) # seen, but NOT accepted
        rendered = self.render_template(self.template_string_1)
        self.assertNotIn(terms.slug, rendered)

    def test_not_show_terms_if_agreed_to_optional_already_seen(self):
        """test if show_terms_if_not_agreed template tag does not load if user agreed optional terms"""
        LOGGER.debug('Test template tag not showing optional terms once agreed to')
        terms = TermsAndConditions.get_active('optional-terms')
        UserTermsAndConditions.objects.create(terms=terms, user=self.user1) # seen and accepted
        rendered = self.render_template(self.template_string_1)
        self.assertNotIn(terms.slug, rendered)

    def test_show_terms_if_not_agreed_on_protected_url_not_agreed(self):
        """Check terms on protected url if not agreed"""
        context = self._make_context('/test')
        result = show_terms_if_not_agreed(context, skip_optional=True)
        terms = TermsAndConditions.get_active(slug=DEFAULT_TERMS_SLUG)
        self.assertEqual(result.get('not_agreed_terms')[0], terms)

    def test_show_terms_if_not_agreed_on_unprotected_url_not_agreed(self):
        """Check terms on unprotected url if not agreed"""
        context = self._make_context('/')
        result = show_terms_if_not_agreed(context)
        self.assertDictEqual(result, {})

    def test_as_template(self):
        """Test as_template template tag"""
        terms = TermsAndConditions.get_active()
        rendered = Template(self.template_string_3).render(Context({'terms': terms}))
        self.assertIn(terms.text, rendered)
