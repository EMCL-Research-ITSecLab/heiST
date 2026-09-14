<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

class DBFunctionsTest extends TestCase {
    private $pdo;
    private $databaseHelper;
    private $logger;
    private $db;

    protected function setUp(): void
    {
        $this->db = new MockPostgresDB();
        $this->pdo = $this->db->getPDO();
    }

    public static function dbFunctionProvider(): array
    {
        return [
            ["SELECT get_user_activities(1301948823, 'web', 'qux', 'qux', 2928566663, 9167911789);"],
            ["SELECT get_user_activities_total_count(1701470440, 'crypto', 'bar', 'baz');"],
            ["SELECT get_total_announcement_count();"],
            ["SELECT get_announcements(9691120026, 6232366780);"],
            [
                "SELECT create_user('baz', 'baz', 'baz', 'baz');",
                "SELECT create_announcement('baz', 'baz', 'qux', 'normal', 'general', 'baz');"
            ],
            ["SELECT update_announcement(1207529919, 'baz', 'baz', 'foo', 'critical', 'security');"],
            ["SELECT announcement_exists(5645415812);"],
            ["SELECT delete_announcement(7144837787);"],
            ["SELECT get_filtered_announcements('important', 'qux', 9695597525, 7335284696);"],
            ["SELECT get_filtered_announcements_count('normal', 'qux');"],
            ["SELECT is_username_taken('qux');"],
            ["SELECT is_email_taken('bar');"],
            ["SELECT create_user('qux', 'qux', 'baz', 'qux');"],
            ["SELECT update_last_login(7662077581);"],
            ["SELECT get_user_password_salt('foo');"],
            ["SELECT authenticate_user('bar', 'baz');"],
            [
                "SELECT create_user('foo', 'foo', 'foo', 'foo');",
                "SELECT change_user_password(5992803582, 'baz', 'foo', 'qux');"
            ],
            ["SELECT is_user_admin(8495262476);"],
            ["SELECT get_user_badges_data(1767917418);"],
            ["SELECT get_user_solved_challenge_count(9769857436);"],
            ["SELECT get_user_solved_challenge_count_in_category(7467960855, 'misc');"],
            ["SELECT get_user_total_points(1599969077);"],
            ["SELECT get_user_earned_badges_count_exclude_one(4597745365, 6041329175);"],
            ["SELECT get_total_badge_count_exclude_one(3699300342);"],
            ["SELECT get_total_badge_count_and_user_earned_count(8463812642);"],
            ["SELECT get_user_running_challenge(3172396416);"],
            ["SELECT get_deployable_conditions(1279224476);"],
            ["SELECT get_creator_id_by_challenge_template(2126340765);"],
            [
                "SELECT create_user('bar', 'bar', 'bar', 'bar');",
                "SELECT create_challenge_template('bar', 'bar', 'misc', 'easy', 'bar', true, 1, 'bar', 'bar');",
                "SELECT create_new_challenge_attempt(1, 1);"
            ],
            ["SELECT mark_attempt_completed(3813916513, 4887700448);"],
            ["SELECT challenge_template_should_be_deleted(9382775402);"],
            ["SELECT delete_challenge_template(2805031016);"],
            ["SELECT validate_and_lock_flag(2237336266, 'bar');"],
            ["SELECT is_duplicate_flag_submission(8178718535, 4037203514, 8610547909);"],
            ["SELECT get_user_submitted_flags_count_for_challenge(9217875792, 4104684190);"],
            ["SELECT get_total_flags_count_for_challenge(6259323417);"],
            ["SELECT get_active_attempt_id(4564968217, 1694629810);"],
            ["SELECT update_running_attempt(5702042437, 6866912610);"],
            [
                "SELECT create_user('baz', 'baz', 'baz', 'baz');",
                "SELECT create_challenge_template('baz', 'baz', 'web', 'hard', 'baz', true, 1, 'baz', 'baz');",
                "SELECT create_challenge_flag(1, 'baz', 'static', 1, 1);",
                "SELECT create_new_completed_attempt(1, 1, 1);"
            ],
            ["SELECT get_recent_unflagged_attempt(8803086608, 1593402162);"],
            ["SELECT update_recent_attempt(9044780824, 9249425042);"],
            ["SELECT get_challenge_template_details(1992086862);"],
            ["SELECT get_challenge_user_status(3300920601, 4669262921);"],
            ["SELECT get_challenge_solution(9233849744);"],
            ["SELECT get_remaining_seconds_for_user_challenge(2409309283, 2866056828);"],
            [
                "SELECT create_user('foo', 'foo', 'foo', 'foo');",
                "SELECT create_challenge_template('foo', 'foo', 'pwn', 'medium', 'foo', true, 1, 'foo', 'foo');",
                "SELECT get_challenge_flags(2865411215);"
            ],
            ["SELECT get_unlocked_challenge_hints(4629297742, 8382313552);"],
            ["SELECT get_completed_flag_ids_for_user(2390182428, 4388258676);"],
            ["SELECT get_entrypoints_for_user_challenge(9934809344);"],
            ["SELECT is_first_blood(9830478988, 5413217896);"],
            ["SELECT get_remaining_extensions_for_user_challenge(2674473257, 3680741336);"],
            ["SELECT get_category_of_challenge_instance(1864279771);"],
            ["SELECT get_user_solved_challenges_in_category(1364606416, 'forensics');"],
            ["SELECT count_user_badges_excluding_one(9772246823, 8174638086);"],
            ["SELECT badge_with_id_exists(1457943079);"],
            ["SELECT user_already_has_badge(4723387455, 8164414595);"],
            [
                "SELECT create_user('qux', 'qux', 'qux', 'qux');",
                "SELECT award_badge_to_user(1, 1);"
            ],
            ["SELECT get_id_and_used_extensions_of_running_challenge(2077780520, 9462618279);"],
            [
                "SELECT create_user('baz', 'baz', 'baz', 'baz');",
                "SELECT create_challenge_template('baz', 'baz', 'reversing', 'easy', 'baz', true, 1, 'baz', 'baz');",
                "INSERT INTO challenges (id, challenge_template_id, subnet, expires_at, used_extensions) VALUES (1, 1, '10.0.0.0/24', NOW() + INTERVAL '1 hour', 0);",
                "SELECT extend_user_challenge_time(9817663176, 1);"
            ],
            ["SELECT get_solve_progress_data(7442727300, 2031369759);"],
            ["SELECT get_elapsed_seconds_for_challenge(4479230532, 9533100130);"],
            ["SELECT get_solved_leaderboard(7982882569);"],
            ["SELECT get_challenge_leaderboard(4883778452, 4827842896, 1114820512);"],
            ["SELECT count_user_challenges_with_same_name('qux', 1745559404);"],
            [
                "SELECT create_user('qux', 'qux', 'qux', 'qux');",
                "SELECT create_challenge_template('qux', 'qux', 'web', 'medium', 'qux', true, 1, 'foo', 'qux');"
            ],
            ["SELECT get_disk_file_id_for_user(9552307442, 'qux');"],
            [
                "SELECT create_user('bar', 'bar', 'bar', 'bar');",
                "SELECT create_challenge_template('bar', 'bar', 'crypto', 'hard', 'bar', true, 1, 'bar', 'bar');",
                "SELECT add_user_disk_file(1, 'bar', 'bar', 'linux');",
                "SELECT create_machine_template(1, 'bar', 1, 4562047925, 7145011170);"
            ],
            [
                "SELECT create_user('foo', 'foo', 'foo', 'foo');",
                "SELECT create_challenge_template('foo', 'foo', 'pwn', 'easy', 'foo', true, 1, 'foo', 'foo');",
                "SELECT add_user_disk_file(1, 'foo', 'foo', 'linux');",
                "SELECT create_machine_template(1, 'foo', 1, 1234567890, 9876543210);",
                "SELECT create_domain_template(900000001, 'foo');"
            ],
            [
                "SELECT create_user('foo', 'foo', 'foo', 'foo');",
                "SELECT create_challenge_template('foo', 'foo', 'pwn', 'easy', 'foo', true, 1, 'foo', 'foo');",
                "SELECT add_user_disk_file(1, 'foo', 'foo', 'linux');",
                "SELECT create_machine_template(1, 'foo', 1, 1234567890, 9876543210);",
                "SELECT create_network_template('foo', true, false, 1);"
            ],
            ["SELECT get_machine_template_id_by_name_and_challenge_id('bar', 4971018084);"],
            [
                "SELECT create_user('baz', 'baz', 'baz', 'baz');",
                "SELECT create_challenge_template('baz', 'baz', 'misc', 'medium', 'baz', true, 1, 'baz', 'baz');",
                "SELECT add_user_disk_file(1, 'baz', 'baz', 'linux');",
                "SELECT create_machine_template(1, 'baz', 1, 5678901234, 4321098765);",
                "SELECT create_network_template('baz', false, true, 1);",
                "SELECT create_network_connection_template(900000001, 1);"
            ],
            [
                "SELECT create_user('foo', 'foo', 'foo', 'foo');",
                "SELECT create_challenge_template('foo', 'foo', 'pwn', 'hard', 'foo', true, 1, 'foo', 'foo');",
                "SELECT create_challenge_flag(1, 'foo', 'baz', 1475904717, 2535230238);"
            ],
            [
                "SELECT create_user('qux', 'qux', 'qux', 'qux');",
                "SELECT create_challenge_template('qux', 'qux', 'forensics', 'medium', 'qux', true, 1, 'qux', 'qux');",
                "SELECT create_challenge_hint(3149280173, 'qux', 8762628755, 4981382206);"
            ],
            ["SELECT get_user_available_disk_files(2129848114);"],
            ["SELECT get_user_data_dashboard(6330633139);"],
            ["SELECT get_progress_data_dashboard(3974823139);"],
            ["SELECT get_total_active_challenges_count_dashboard();"],
            ["SELECT get_user_activity_dashboard(7745717373, 8022548074);"],
            ["SELECT get_user_badges_data_dashboard(2456343715);"],
            ["SELECT get_user_progress_data_dashboard(6202221934);"],
            ["SELECT get_challenges_data_dashboard(7167162641);"],
            ["SELECT get_timeline_data_dashboard(6571596304, '2023-01-01', '2023-12-31', 'week', 'YYYY-MM-DD');"],
            ["SELECT get_announcements_data_dashboard();"],
            ["SELECT get_challenge_template_id_from_challenge_id(2511200179);"],
            ["SELECT get_running_challenge_data_dashboard(1960955733, 7041630383);"],
            ["SELECT get_user_disk_files(8750297916);"],
            ["SELECT is_duplicate_file_name(3653785646, 'baz');"],
            [
                "SELECT create_user('foo', 'foo', 'foo', 'foo');",
                "SELECT add_user_disk_file(1, 'foo', 'bar');"
            ],
            ["SELECT get_filename_by_id(5346693834, 3522567711);"],
            ["SELECT delete_user_disk_file(3099008394, 4680790154);"],
            ["SELECT explore_challenges('forensics', 'easy', 'qux', 'foo', 9689940695, 6840322549);"],
            ["SELECT explore_challenges_count('misc', 'hard', 'qux');"],
            ["SELECT get_user_solved_challenge(9022717629, 8248346245);"],
            ["SELECT get_creator_id_by_challenge_id(2502949882);"],
            ["SELECT get_total_leaderboard_entries_for_author(6828186141);"],
            ["SELECT get_challenge_template_id_by_name_with_possible_exclude('qux', 5709437657);"],
            ["SELECT get_challenge_template_data_for_deletion(3574375603, 3316218302);"],
            ["SELECT challenge_template_is_marked_for_deletion(8748377759);"],
            ["SELECT update_challenge_template(7595970897, 'foo', 'qux', 'forensics', 'medium', 'foo', 'qux', true);"],
            ["SELECT restore_challenge_template(3455157587);"],
            ["SELECT verify_challenge_template_ownership_for_deletion(5050004617, 9058860875);"],
            ["SELECT mark_challenge_template_for_deletion(5777139315);"],
            ["SELECT get_running_instances_of_challenge_template(9424946684);"],
            ["SELECT count_active_deployments_of_challenge_template(8425663675);"],
            ["SELECT mark_challenge_template_for_soft_deletion(3455006454);"],
            ["SELECT get_challenge_templates_for_management(4391417745);"],
            ["SELECT get_challenge_template_count_for_user(8723104887);"],
            ["SELECT get_active_deployments_of_challenge_templates_by_user(2106973747);"],
            ["SELECT get_total_deployments_of_challenge_templates_by_user(9000745921);"],
            ["SELECT get_average_completion_time_of_challenge_templates_by_user(7505408762);"],
            ["SELECT get_basic_profile_data(5821939130);"],
            ["SELECT get_user_rank(5950682104, 4654970903);"],
            ["SELECT get_profile_stats(2059669969);"],
            ["SELECT get_profile_badges(8534711055);"],
            ["SELECT get_total_badges_count();"],
            ["SELECT get_recent_activity(9860052981, 3993591947);"],
            ["SELECT is_username_taken_by_other_user(9556486541, 'qux');"],
            ["SELECT update_username(6065794984, 'foo');"],
            ["SELECT is_email_taken_by_other_user(1193974513, 'foo');"],
            ["SELECT update_email(1432407472, 'baz');"],
            ["SELECT user_profile_exists(3782107705);"],
            [
                "SELECT create_user('qux', 'qux', 'qux', 'qux');",
                "SELECT update_full_name(1, 'qux');"
            ],
            [
                "SELECT create_user('foo', 'foo', 'foo', 'foo');",
                "SELECT update_bio(1, 'foo');"
            ],
            [
                "SELECT create_user('bar', 'bar', 'bar', 'bar');",
                "SELECT update_urls(1, 'qux', 'qux', 'baz');"
            ],
            ["SELECT get_user_avatar(4936933701);"],
            ["SELECT update_user_avatar(7456389033, 'baz');"],
            ["SELECT get_all_challenge_categories();"],
            ["SELECT get_challenge_count_by_categories();"],
            ["SELECT get_user_solved_challenge_count_by_categories(3956825696);"],
            ["SELECT get_user_disk_files_display_data(3804938684);"],
            [
                "SELECT create_user('foo', 'foo', 'foo', 'foo');",
                "SELECT delete_user_disk_files(1, 4780546318, 'foo');"
            ],
            [
                "SELECT create_user('baz', 'baz', 'baz', 'baz');",
                "SELECT delete_user_data(1, 'baz');"
            ],
            ["SELECT get_header_data(2338235801);"],
            ["SELECT get_id_by_username('qux');"],
            ["SELECT get_public_profile_data(4177794686);"],
            ["SELECT get_active_challenge_templates_by_category();"],
            ["SELECT get_user_earned_badges_data(7322818132);"],
            ["SELECT get_expired_challenge_data();"],
        ];
    }

    #[DataProvider('dbFunctionProvider')] public function testDBFunctions(string $query): void {
        $stmt = $this->pdo->prepare($query);
        $this->assertNotFalse($stmt, "Failed to prepare query: $query");
        $result = $stmt->execute();
        $this->assertTrue($result, "Failed to execute query: $query");
    }

    public function testStaticFunctionLinting(): void {
        $this->db->installLintingTools();

        $stmt = $this->pdo->prepare("CREATE EXTENSION IF NOT EXISTS plpgsql_check;");
        $this->assertNotFalse($stmt, "Failed to prepare query for creating plpgsql_check extension");
        $result = $stmt->execute();

        $scanQuery = "
            SELECT
                (SELECT * FROM plpgsql_check_function(p.oid)) AS lint_results,
                p.proname
            FROM pg_proc p
            JOIN pg_language l ON p.prolang = l.oid
            WHERE l.lanname = 'plpgsql'
              AND p.prorettype != 'trigger'::regtype
              AND p.pronamespace = 'public'::regnamespace;
        ";
        $stmt = $this->pdo->prepare($scanQuery);
        $this->assertNotFalse($stmt, "Failed to prepare query for scanning functions with plpgsql_check");
        $result = $stmt->execute();
        $this->assertTrue($result, "Failed to execute function scan query with plpgsql_check");

        print_r($stmt->fetchAll());
    }
}