"""Administrator workflows against the built UI and synthetic HTTP fixtures."""
import json

from tests.browser.support import BrowserFixture
from tests.browser.showcase_data import responses


class ManagementBrowserTests(BrowserFixture):
    def setUp(self):
        super().setUp()
        self.role='admin'
        self.responses=responses()

    def settled(self,path):
        self.visit(path)
        self.page.wait_for_function("!document.querySelector('main .loading')")

    def test_fresh_unverified_coverage_is_distinct_from_missing_or_stale_evidence(self):
        for status in ('unknown', 'stale', 'unavailable'):
            with self.subTest(status=status):
                self.responses['admin/operations'] = {'success': True, 'data': {
                    'database': 'ready', 'archive': {'status': 'success'},
                    'monitoring': {'status': status, 'checks': [
                        {'id': 'host.end_to_end', 'label': 'End-to-end', 'state': 'unknown', 'summary': 'Canary required'}]}}}
                self.settled('/operations')
                main = self.page.get_by_role('main')
                warning = main.get_by_text('Current monitoring evidence is unavailable or stale.', exact=True)
                if status == 'unknown':
                    self.assertEqual(warning.count(), 0)
                    main.get_by_text('1 checks need verification.', exact=False).wait_for()
                    main.get_by_text('No failed checks in the current monitoring receipt.', exact=True).wait_for()
                else:
                    warning.wait_for()
                    self.assertEqual(main.get_by_text('No failed checks in the current monitoring receipt.', exact=True).count(), 0)

    def test_vm_action_previews_exact_target_and_reports_queued_not_finished(self):
        self.settled('/manage-instances?instance=101')
        self.page.get_by_role('button',name='Shut down',exact=True).first.click()
        dialog=self.page.get_by_role('dialog')
        dialog.get_by_text('100000101',exact=False).wait_for()
        dialog.get_by_role('button',name='Shut down',exact=True).click()
        dialog.wait_for(state='detached')
        self.assertEqual(self.mutations[-1][0],'admin/instances/101/machines/100000101')
        self.assertEqual(json.loads(self.mutations[-1][1]),{'action':'shutdown','expected':'a'*64})
        self.page.get_by_role('link',name='View progress',exact=True).wait_for()
        self.assertIn('queued',self.page.get_by_role('main').inner_text().lower())

    def test_failed_preview_blocks_confirmation_and_can_be_cancelled(self):
        self.context.route('**/api/admin/instances/101/preview?**',lambda route:route.fulfill(status=409,json={'success':False,'message':'Instance changed; refresh'}))
        self.settled('/manage-instances?instance=101')
        self.page.get_by_role('button',name='Rebuild',exact=True).first.click()
        dialog=self.page.get_by_role('dialog')
        dialog.get_by_text('Instance changed; refresh',exact=True).wait_for()
        self.assertTrue(dialog.get_by_role('button',name='Rebuild',exact=True).is_disabled())
        dialog.get_by_role('button',name='Cancel',exact=True).click()
        self.assertEqual(self.mutations,[])

    def test_reconciliation_requires_checks_and_exact_operation_id(self):
        self.settled('/operations?tab=jobs&scope=user&resource=2')
        self.page.locator('summary').filter(has_text='admin_rebuild').click()
        self.page.get_by_role('button',name='Record reconciliation',exact=True).click()
        dialog=self.page.get_by_role('dialog')
        confirm=dialog.get_by_role('button',name='Mark reconciled',exact=True)
        self.assertTrue(confirm.is_disabled())
        dialog.get_by_label('Recovery checks',exact=True).fill('Verified VM and assignment state on disposable fixture')
        dialog.get_by_label('Type operation ID',exact=True).fill('a'*32)
        self.assertTrue(confirm.is_disabled())
        dialog.get_by_label('Type operation ID',exact=True).fill('b'*32)
        confirm.click();dialog.wait_for(state='detached')
        endpoint,body,_=self.mutations[-1]
        self.assertEqual(endpoint,'admin/jobs/'+'b'*32+'/resolve')
        self.assertEqual(json.loads(body)['confirmation'],'b'*32)

    def test_only_queued_history_offers_cancellation(self):
        operation=self.responses['admin/jobs/user/2']['data']['operations'][1]
        operation['state']='QUEUED'
        self.settled('/operations?tab=jobs&scope=user&resource=2')
        self.page.locator('summary').filter(has_text='admin_rebuild').click()
        self.page.get_by_role('button',name='Cancel queued operation',exact=True).click()
        self.page.get_by_role('dialog').get_by_role('button',name='Cancel operation',exact=True).click()
        self.assertEqual(self.mutations[-1][0],'admin/jobs/'+'b'*32+'/cancel')
        operation['state']='RUNNING'
        self.settled('/operations?tab=jobs&scope=user&resource=2')
        self.page.locator('summary').filter(has_text='admin_rebuild').click()
        self.assertEqual(self.page.get_by_role('button',name='Cancel queued operation',exact=True).count(),0)

    def test_pool_policy_uses_revision_and_bounds_manual_target(self):
        self.settled('/operations?tab=capacity')
        self.page.get_by_role('button',name='Configure pool',exact=True).click()
        dialog=self.page.get_by_role('dialog')
        copies=dialog.get_by_label('Ready copies',exact=True)
        self.assertTrue(copies.is_disabled())
        dialog.get_by_label('Use a manual pool target',exact=True).check()
        copies.fill('11')
        self.assertTrue(dialog.get_by_role('button',name='Save pool policy',exact=True).is_disabled())
        copies.fill('2');dialog.get_by_role('button',name='Save pool policy',exact=True).click()
        dialog.wait_for(state='detached')
        self.assertEqual(self.mutations[-1][0],'admin/pools/4')
        self.assertEqual(json.loads(self.mutations[-1][1]),{'size':2,'enabled':True,'expected_revision':0})

    def test_revision_inspection_keeps_flag_values_out_of_rendered_page(self):
        self.settled('/manage-ctf?exercise=4')
        self.page.get_by_role('button',name='Inspect revision',exact=True).click()
        self.page.get_by_role('heading',name='Revision 1',exact=True).wait_for()
        self.assertEqual(self.page.get_by_role('img',name='Challenge network preview').count(),1)
        self.assertNotIn('synthetic-private-value',self.page.get_by_role('main').inner_text())
        self.page.get_by_role('button',name='Clone as draft',exact=True).click()
        dialog=self.page.get_by_role('dialog')
        dialog.get_by_label('New draft name',exact=True).fill('')
        self.assertTrue(dialog.get_by_role('button',name='Clone draft',exact=True).is_disabled())
        dialog.get_by_role('button',name='Cancel',exact=True).click()
        self.assertEqual(self.mutations,[])

    def test_capacity_uncertainty_and_maintenance_do_not_invent_acceptance(self):
        self.responses['admin/overview']['data']['host']={'status':'unavailable'}
        self.settled('/operations?tab=capacity')
        self.page.get_by_text('Live host measurements could not be verified.',exact=True).wait_for()
        self.settled('/operations?tab=maintenance')
        self.assertIn('not configured',self.page.get_by_role('main').inner_text().lower())
        self.assertIn('RECOVERY_REQUIRED',self.page.get_by_role('main').inner_text())
        self.assertEqual(self.mutations,[])
