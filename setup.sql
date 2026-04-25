CREATE DATABASE IF NOT EXISTS tara_system;
USE tara_system;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'cashier', 'viewer') DEFAULT 'cashier',
    full_name VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    type ENUM('income', 'expense') NOT NULL,
    description VARCHAR(255),
    transaction_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

INSERT INTO users (username, password, role, full_name) 
VALUES ('admin', SHA2('admin123', 256), 'admin', 'System Admin')
ON DUPLICATE KEY UPDATE id=id;

SELECT * FROM users;