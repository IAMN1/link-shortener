from link_shortener.infrastructure.core.logging_config import StructLogConfig, setup_logging

# ------------------------------------------------------------------
# TestStructLogConfig
# ------------------------------------------------------------------
class TestStructLogConfig:
    """Tests for StructLogConfig."""

    def test_struct_log_config(self, test_config):
        """
        Should initialize StructLogConfig 
        correctly from config dict.
        """

        # Arrange
        config_dict = {
            'LOG_DIR': test_config.LOG_DIR,
            'LOG_FILENAME': test_config.LOG_FILENAME,
            'LOG_DATE_FORMAT': test_config.LOG_DATE_FORMAT,
            'LOG_MAX_BYTES': test_config.LOG_MAX_BYTES,
            'LOG_BACKUP_FILES_COUNT': test_config.LOG_BACKUP_FILES_COUNT,
            'LOG_TO_CONSOLE': test_config.LOG_TO_CONSOLE,
            'LOG_TO_FILE': test_config.LOG_TO_FILE,
            'DEBUG': test_config.DEBUG,
        }

        # Act
        log_config = StructLogConfig(config_dict)

        assert log_config.log_dir == test_config.LOG_DIR
        assert log_config.should_log_to_file == (test_config.LOG_TO_FILE and bool(test_config.LOG_DIR))
        if log_config.should_log_to_file:
            path = log_config.get_log_file_path()
            assert path.startswith(test_config.LOG_DIR)
            assert test_config.LOG_FILENAME in path


    def test_setup_logging(self, mocker, tmp_path, test_config):
        """Should set up logging configuration."""

        # Arrange
        app = mocker.MagicMock()
        app.config = test_config.__dict__.copy()
        app.config["LOG_DIR"] = str(tmp_path)

        mock_setup = mocker.patch(
            "link_shortener.infrastructure.core.logging_config._setup_structlog"
        )
        mock_makedirs = mocker.patch("os.makedirs")

        # Act
        setup_logging(app)

        # Assert
        mock_makedirs.assert_called_once_with(str(tmp_path), exist_ok=True)
        mock_setup.assert_called_once()