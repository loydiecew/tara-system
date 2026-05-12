-- TARA System Seed Data

-- plans (4 rows)
INSERT INTO `plans` (`id`, `name`, `slug`, `price_monthly`, `max_users`, `created_at`) VALUES (1, 'Starter', 'starter', 0.00, 1, 2026-05-09 19:29:20);
INSERT INTO `plans` (`id`, `name`, `slug`, `price_monthly`, `max_users`, `created_at`) VALUES (2, 'Essentials', 'essentials', 199.00, 1, 2026-05-09 19:29:20);
INSERT INTO `plans` (`id`, `name`, `slug`, `price_monthly`, `max_users`, `created_at`) VALUES (3, 'Professional', 'professional', 599.00, 3, 2026-05-09 19:29:20);
INSERT INTO `plans` (`id`, `name`, `slug`, `price_monthly`, `max_users`, `created_at`) VALUES (4, 'Suite', 'suite', 1499.00, 10, 2026-05-09 19:29:20);

-- chart_of_accounts (12 rows)
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (1, '1000', 'Cash', 'asset', 'debit', NULL, 1, 2026-04-28 19:52:22);
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (2, '1100', 'Accounts Receivable', 'asset', 'debit', NULL, 1, 2026-04-28 19:52:22);
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (3, '1200', 'Inventory', 'asset', 'debit', NULL, 1, 2026-04-28 19:52:22);
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (4, '2000', 'Accounts Payable', 'liability', 'credit', NULL, 1, 2026-04-28 19:52:22);
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (5, '3000', 'Owner\'s Equity', 'equity', 'credit', NULL, 1, 2026-04-28 19:52:22);
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (6, '4000', 'Sales Revenue', 'revenue', 'credit', NULL, 1, 2026-04-28 19:52:22);
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (7, '4100', 'Service Income', 'revenue', 'credit', NULL, 1, 2026-04-28 19:52:22);
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (8, '5000', 'Cost of Goods Sold', 'expense', 'debit', NULL, 1, 2026-04-28 19:52:22);
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (9, '5100', 'Rent Expense', 'expense', 'debit', NULL, 1, 2026-04-28 19:52:22);
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (10, '5200', 'Utilities Expense', 'expense', 'debit', NULL, 1, 2026-04-28 19:52:22);
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (11, '5300', 'Supplies Expense', 'expense', 'debit', NULL, 1, 2026-04-28 19:52:22);
INSERT INTO `chart_of_accounts` (`id`, `code`, `name`, `type`, `normal_balance`, `parent_id`, `is_active`, `created_at`) VALUES (12, '5400', 'Salary Expense', 'expense', 'debit', NULL, 1, 2026-04-28 19:52:22);

-- categories (21 rows)
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (1, NULL, 'Sales Revenue', 'income', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (2, NULL, 'Service Income', 'income', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (3, NULL, 'Interest Income', 'income', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (4, NULL, 'Other Income', 'income', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (5, NULL, 'Rent', 'expense', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (6, NULL, 'Salaries & Wages', 'expense', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (7, NULL, 'Utilities', 'expense', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (8, NULL, 'Supplies', 'expense', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (9, NULL, 'Marketing', 'expense', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (10, NULL, 'Equipment', 'expense', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (11, NULL, 'Travel', 'expense', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (12, NULL, 'Other Expense', 'expense', NULL, 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (13, NULL, 'Food Supplies', 'expense', 'restaurant', 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (14, NULL, 'Kitchen Equipment', 'expense', 'restaurant', 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (15, NULL, 'Dine-in Sales', 'income', 'restaurant', 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (16, NULL, 'Takeout Sales', 'income', 'restaurant', 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (17, NULL, 'Delivery Sales', 'income', 'restaurant', 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (18, NULL, 'Inventory Purchase', 'expense', 'retail', 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (19, NULL, 'Store Rent', 'expense', 'retail', 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (20, NULL, 'Walk-in Sales', 'income', 'retail', 0, 2026-04-24 21:35:16);
INSERT INTO `categories` (`id`, `user_id`, `name`, `type`, `industry`, `is_custom`, `created_at`) VALUES (21, NULL, 'Online Sales', 'income', 'retail', 0, 2026-04-24 21:35:16);

