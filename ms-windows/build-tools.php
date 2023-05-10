<?php
	// Tools to build/generate OpenSSL installer packages for Windows.

	if (!isset($_SERVER["argc"]) || !$_SERVER["argc"])
	{
		echo "This file is intended to be run from the command-line.";

		exit();
	}

	// Temporary root.
	$rootpath = str_replace("\\", "/", dirname(__FILE__));

	// Some essential support libraries are in /support.
	require_once $rootpath . "/support/cli.php";

	// Process the command-line options.
	$options = array(
		"shortmap" => array(
			"s" => "suppressoutput",
			"?" => "help"
		),
		"rules" => array(
			"suppressoutput" => array("arg" => false),
			"help" => array("arg" => false)
		),
		"allow_opts_after_param" => false
	);
	$args = CLI::ParseCommandLine($options);

	if (isset($args["opts"]["help"]))
	{
		echo "The OpenSSL tool to build/generate installer packages for Windows.\n";
		echo "Purpose:  Download and verify sources, build OpenSSL, and generate installers.\n";
		echo "\n";
		echo "A relatively recent Intel/AMD CPU with at least 8 performance cores is highly recommended plus several GB of available storage.\n";
		echo "\n";
		echo "This tool is question/answer enabled.  Just running it will provide a guided interface.  It can also be run entirely from the command-line if you know all the answers.\n";
		echo "\n";
		echo "Syntax:  " . $args["file"] . " [options] [cmd [cmdoptions]]\n";
		echo "Options:\n";
		echo "\t-s   Suppress most output.  Useful for capturing JSON output.\n";
		echo "\n";
		echo "Examples:\n";
		echo "\tphp " . $args["file"] . "\n";
		echo "\tphp " . $args["file"] . " init 3.1\n";
		echo "\tphp " . $args["file"] . " save-profile 3.1 x86\n";
		echo "\tphp " . $args["file"] . " prepare 3.1.0\n";
		echo "\tphp " . $args["file"] . " build-all 3.1.0\n";
		echo "\tphp " . $args["file"] . " build-all 1.1.1t 3.0.8 3.1.0\n";

		exit();
	}

	$origargs = $args;
	$suppressoutput = (isset($args["opts"]["suppressoutput"]) && $args["opts"]["suppressoutput"]);

	// Check critical dependencies.
	$os = php_uname("s");
	$windows = (strtoupper(substr($os, 0, 3)) == "WIN");

	if (!$windows)  CLI::DisplayError("This script currently only runs on Windows.");
	if (!extension_loaded("zlib"))  CLI::DisplayError("Please enable the 'zlib' extension in your system's 'php.ini' file.  zlib is used by this tool to decompress .tar.gz and .zip files.");
	if (!extension_loaded("zip"))  CLI::DisplayError("Please enable the 'zip' extension in your system's 'php.ini' file.  zip is used by this tool to decompress .zip files.");
	if (!extension_loaded("openssl"))  CLI::DisplayError("Please enable the 'openssl' extension in your system's 'php.ini' file.  openssl is used by this tool to connect to servers to download source files and dependencies.  Yes, this is weird.");

	// Get the command.
	$cmds = array(
		"init" => "Initialize a specific base version from a template to download, verify, extract, and configure dependencies",
		"init-test" => "Verify that all possible downloads for a base version are still working and have correct hashes",
		"save-profile" => "Validate and save an environment profile for a specific base version and architecture",
		"prepare" => "Download a source tarball for a specific version, verify and extract, and generate versioned installer scripts",
		"build-all" => "Perform a build for a specific version for all architectures using saved environment profiles and localized dependencies",
		"build" => "Perform a build for a specific version and architecture using saved environment profiles and localized dependencies",
	);

	$cmd = CLI::GetLimitedUserInputWithArgs($args, false, "Command", false, "Available commands:", $cmds, true, $suppressoutput);

	@mkdir($rootpath . "/temp/logs", 0775, true);
	@mkdir($rootpath . "/versions", 0775, true);

	// Base version information is stored in:  /templates/X.X/info.json
	function GetBaseVersions()
	{
		global $rootpath;

		$versions = array();

		$dir = opendir($rootpath . "/templates");
		if (!$dir)  CLI::DisplayError("Failed to open 'templates' directory.");

		while (($file = readdir($dir)) !== false)
		{
			$filename = $rootpath . "/templates/" . $file . "/info.json";

			if ($file !== "." && $file !== ".." && file_exists($filename))
			{
				$verdata = json_decode(file_get_contents($filename), true);

				if (!is_array($verdata))  CLI::DisplayError("JSON decoding failed for '" . $filename . "'.  " . json_last_error_msg(), false, false);
				else  $versions[$file] = $verdata["name"];
			}
		}

		closedir($dir);

		if (!count($versions))  CLI::DisplayError("No version templates found.");

		return $versions;
	}

	// Loads base version information and expands dependencies.  The expansion mechanism significantly simplifies the JSON information file.
	function LoadAndExpandBaseVersionInfo($basever)
	{
		global $rootpath;

		$filename = $rootpath . "/templates/" . $basever . "/info.json";

		$verdata = json_decode(file_get_contents($filename), true);
		if (!is_array($verdata))  CLI::DisplayError("Unable to decode JSON in '" . $filename . "'.");

		if (!isset($verdata["architectures"]) || !count($verdata["architectures"]))  CLI::DisplayError("JSON data does not specify any architectures.");

		$archdepmap = array();

		foreach ($verdata["architectures"] as $archinfo)
		{
			foreach ($archinfo["dependencies"] as $depinfo)
			{
				if (!isset($depinfo["expand_from"]))  $archdepmap[$archinfo["architecture"] . "|" . $depinfo["name"]] = $depinfo;
			}
		}

		foreach ($verdata["architectures"] as &$archinfo)
		{
			$dependencies = array();

			foreach ($archinfo["dependencies"] as $depinfo)
			{
				if (!isset($depinfo["expand_from"]))  $dependencies[] = $depinfo;
				else if (isset($archdepmap[$depinfo["expand_from"] . "|" . $depinfo["name"]]))  $dependencies[] = $archdepmap[$depinfo["expand_from"] . "|" . $depinfo["name"]];
				else  CLI::DisplayError("Unable to expand '" . $depinfo["name"] . "' for '" . $archinfo["architecture"] . "' in '" . $filename . "'.  Mapping does not exist.");
			}

			$archinfo["dependencies"] = $dependencies;
		}

		return $verdata;
	}

	// Extracts a supported base version and specific version from user input.
	function GetSpecificVersionInput($inputmsg)
	{
		global $args, $suppressoutput;

		$versions = GetBaseVersions();

		do
		{
			$ver = CLI::GetUserInputWithArgs($args, "version", "Version", false, $inputmsg, $suppressoutput);

			$verparts = explode(".", $ver);

			$basever = false;
			foreach ($versions as $ver2 => $val)
			{
				$verparts2 = explode(".", $ver2);
				if (count($verparts) >= count($verparts2) && $ver !== $ver2)
				{
					$found = true;
					foreach ($verparts2 as $num => $part)
					{
						if ((int)$part !== (int)$verparts[$num])  $found = false;
					}

					if ($found)  $basever = $ver2;
				}
			}

			if ($basever === false)  CLI::DisplayError("A supported base version was not found for " . $ver . ".", false, false);
		} while ($basever === false);

		return array("basever" => $basever, "ver" => $ver);
	}

	// Returns the list of saved architecture environment profiles for a base version.
	function GetProfileList($basever, $verdata)
	{
		global $rootpath;

		$profiles = array();

		$profiledir = $rootpath . "/versions/" . $basever . "/profiles";
		foreach ($verdata["architectures"] as $archinfo)
		{
			if (file_exists($profiledir . "/" . $archinfo["architecture"] . ".json"))  $profiles[$archinfo["architecture"]] = $archinfo["name"];
		}

		return $profiles;
	}

	function CopyFiles($srcdir, $destdir, $recurse, $pattern = "/.*/", $flatten = false)
	{
		$dir = opendir($srcdir);
		if ($dir)
		{
			while (($file = readdir($dir)) !== false)
			{
				if ($file !== "." && $file !== "..")
				{
					if (is_dir($srcdir . "/" . $file))
					{
						if ($recurse)  CopyFiles($srcdir . "/" . $file, ($flatten ? $destdir : $destdir . "/" . $file), true, $pattern);
					}
					else if (preg_match($pattern, $file))
					{
						@mkdir($destdir, 0775, true);

						copy($srcdir . "/" . $file, $destdir . "/" . $file);
					}
				}
			}

			closedir($dir);
		}
	}

	function CopyDirectory($srcdir, $destdir, $recurse = true)
	{
		$srcdir = rtrim(str_replace("\\", "/", $srcdir), "/");
		$destdir = rtrim(str_replace("\\", "/", $destdir), "/");

		@mkdir($destdir, 0775, true);

		CopyFiles($srcdir, $destdir, $recurse);
	}

	function CopyTextFile($srcfile, $destfile)
	{
		if (!file_exists($srcfile) && file_exists($srcfile . ".md"))  $srcfile .= ".md";
		if (!file_exists($srcfile) && file_exists($srcfile . ".txt"))  $srcfile .= ".txt";

		$data = file_get_contents($srcfile);

		$data = str_replace("\r\n", "\n", $data);
		$data = str_replace("\r", "\n", $data);
		$data = str_replace("\n", "\r\n", $data);

		file_put_contents($destfile, $data);
	}

	function DeleteDirectory($path)
	{
		$dir = @opendir($path);
		if ($dir)
		{
			while (($file = readdir($dir)) !== false)
			{
				if ($file !== "." && $file !== "..")
				{
					if (is_dir($path . "/" . $file))  DeleteDirectory($path . "/" . $file);
					else  @unlink($path . "/" . $file);
				}
			}

			closedir($dir);

			@rmdir($path);
		}
	}

	// Returns a PHP variable-free environment.
	function GetCleanEnvironment()
	{
		$ignore = array(
			"PHP_SELF" => true,
			"SCRIPT_NAME" => true,
			"SCRIPT_FILENAME" => true,
			"PATH_TRANSLATED" => true,
			"DOCUMENT_ROOT" => true,
			"REQUEST_TIME_FLOAT" => true,
			"REQUEST_TIME" => true,
			"argv" => true,
			"argc" => true,
		);

		$result = array();
		foreach ($_SERVER as $key => $val)
		{
			if (!isset($ignore[$key]) && is_string($val))  $result[$key] = $val;
		}

		return $result;
	}

	function GetEnvironmentKeymap($env)
	{
		$result = array();
		foreach ($env as $key => $val)  $result[strtoupper($key)] = $key;

		return $result;
	}

	// Runs a simple command and returns the results.
	function RunCommand($cmd, $errorfilename = false, $startdir = NULL, $env = NULL)
	{
		$os = php_uname("s");
		$windows = (strtoupper(substr($os, 0, 3)) == "WIN");

		$descriptors = array(
			0 => array("file", ($windows ? "NUL" : "/dev/null"), "r"),
			1 => array("pipe", "w"),
			2 => array("file", ($errorfilename !== false ? $errorfilename : ($windows ? "NUL" : "/dev/null")), "w")
		);

		$proc = @proc_open($cmd, $descriptors, $pipes, $startdir, $env, array("suppress_errors" => true, "bypass_shell" => true));

		if (!is_resource($proc) || !isset($pipes[1]))  return false;

		if (isset($pipes[0]))  @fclose($pipes[0]);
		if (isset($pipes[2]))  @fclose($pipes[2]);

		$fp = $pipes[1];

		$result = "";

		while (!feof($fp))
		{
			$data = @fread($fp, 65536);
			if ($data !== false)  $result .= $data;
		}

		fclose($fp);

		@proc_close($proc);

		return $result;
	}

	function DownloadFileCallback($response, $data, $opts)
	{
		global $suppressoutput;

		if ($response["code"] == 200)
		{
			$size = ftell($opts);
			fwrite($opts, $data);

			if (!$suppressoutput && $size % 1000000 > ($size + strlen($data)) % 1000000)  echo ".";
		}

		return true;
	}

	$downloadsverified = array();

	// Downloads a file to the /temp directory and verifies it.
	function DownloadTempFile($pathmap, $downloadinfo, $downloadkey)
	{
		global $rootpath, $suppressoutput, $downloadsverified;

		if (isset($downloadinfo[$downloadkey . "_temp"]))  $tempfile = $downloadinfo[$downloadkey . "_temp"];
		else
		{
			$url = str_replace(array_keys($pathmap), array_values($pathmap), $downloadinfo[$downloadkey]);

			$pos = strrpos($url, "/");
			$tempfile = substr($url, $pos + 1);
		}

		$tempfilename = $rootpath . "/temp/" . $tempfile;

		// Download file.
		if (!file_exists($tempfilename))
		{
			$url = str_replace(array_keys($pathmap), array_values($pathmap), $downloadinfo[$downloadkey]);

			if (!$suppressoutput)  echo "Downloading " . $downloadinfo["name"] . " '" . $url . "'...";

			require_once $rootpath . "/support/web_browser.php";

			$web = new WebBrowser();

			$fp = fopen($tempfilename, "wb");

			$web = new WebBrowser();
			$options = array(
				"read_body_callback" => "DownloadFileCallback",
				"read_body_callback_opts" => $fp
			);

			$result = $web->Process($url, $options);
			echo "\n";

			fclose($fp);

			if (!$result["success"])  CLI::DisplayError("Error retrieving URL.", $result);
			if ($result["response"]["code"] != 200)  CLI::DisplayError("Error retrieving URL.  Server returned:  " . $result["response"]["code"] . " " . $result["response"]["meaning"]);
		}

		// Verify file integrity.
		if (isset($downloadinfo[$downloadkey . "_sha256"]) && !isset($downloadsverified[$tempfilename . "|sha256"]))
		{
			if (!$suppressoutput)  echo "Verifying '" . $tempfilename . "'...\n";

			$hash = hash_file("sha256", $tempfilename);
			if ($hash !== $downloadinfo[$downloadkey . "_sha256"])  CLI::DisplayError("The SHA256 for '" . $tempfilename . "' is '" . $hash . "'.  Expected '" . $downloadinfo[$downloadkey . "_sha256"] . "'.");

			$downloadsverified[$tempfilename . "|sha256"] = true;
		}

		if (isset($downloadinfo[$downloadkey . "_sha256_url"]) && !isset($downloadsverified[$tempfilename . "|sha256_url"]))
		{
			if (!$suppressoutput)  echo "Verifying '" . $tempfilename . "'...\n";

			require_once $rootpath . "/support/web_browser.php";

			$url = str_replace(array_keys($pathmap), array_values($pathmap), $downloadinfo[$downloadkey . "_sha256_url"]);

			$web = new WebBrowser();

			$result = $web->Process($url);

			if (!$result["success"])  CLI::DisplayError("Error retrieving URL.", $result);
			if ($result["response"]["code"] != 200)  CLI::DisplayError("Error retrieving URL.  Server returned:  " . $result["response"]["code"] . " " . $result["response"]["meaning"]);

			$hash = hash_file("sha256", $tempfilename);
			if ($hash !== strtolower(trim($result["body"])))  CLI::DisplayError("The SHA256 for '" . $tempfilename . "' is '" . $hash . "'.  Expected '" . strtolower(trim($result["body"])) . "'.");

			$downloadsverified[$tempfilename . "|sha256_url"] = true;
		}
	}

	// Applies PATH and other environment variables from the configuration for a dependency.
	function ApplyDependencyEnvironment(&$tempenv, &$tempenvkeymap, $pathmap, $depinfo)
	{
		// Remove dependency matches from the path.
		$paths = explode(PATH_SEPARATOR, (isset($tempenv[$tempenvkeymap["PATH"]]) ? $tempenv[$tempenvkeymap["PATH"]] : ""));
		$paths2 = array();
		foreach ($paths as $path)
		{
			$path = trim($path);
			if ($path !== "" && !file_exists($path . "/" . $depinfo["verify"]))  $paths2[] = $path;
		}
		if (!isset($tempenvkeymap["PATH"]))  $tempenvkeymap["PATH"] = "Path";
		$tempenv[$tempenvkeymap["PATH"]] = implode(PATH_SEPARATOR, $paths);

		// Append dependency paths to the path.
		if (isset($depinfo["env_paths"]))
		{
			foreach ($depinfo["env_paths"] as $path)
			{
				$path = str_replace(array_keys($pathmap), array_values($pathmap), $path);
				$path = str_replace("/", "\\", $path);

				$tempenv[$tempenvkeymap["PATH"]] .= ";" . $path;

				putenv($tempenvkeymap["PATH"] . "=" . $tempenv[$tempenvkeymap["PATH"]]);
			}
		}

		// Other environment variables.
		if (isset($depinfo["env_extras"]))
		{
			foreach ($depinfo["env_extras"] as $key => $val)
			{
				if (strpos($val, "[[") !== false && strpos($val, "]]") !== false)
				{
					$val = str_replace(array_keys($pathmap), array_values($pathmap), $val);
					$val = str_replace("/", "\\", $val);
				}

				if (isset($tempenvkeymap[strtoupper($key)]))  unset($tempenv[$tempenvkeymap[strtoupper($key)]]);

				$tempenv[$key] = $val;
			}
		}
	}

	// Verifies that a dependency appears to be functioning correctly.
	function VerifyDependency($pathmap, $depinfo, $failpreferred)
	{
		global $rootpath, $suppressoutput;

		if (!isset($depinfo["verify"]))  return true;

		$tempenv = GetCleanEnvironment();
//		$tempenv["OPENSSL_DEPS_DIR"] = str_replace("/", "\\", $pathmap["[[DEPS_DIR]]"]);

		$tempenvkeymap = GetEnvironmentKeymap($tempenv);

		ApplyDependencyEnvironment($tempenv, $tempenvkeymap, $pathmap, $depinfo);

		$cmd = str_replace(array_keys($pathmap), array_values($pathmap), $depinfo["verify"]);
		$cmd = escapeshellarg(str_replace("/", "\\", $cmd));
		if (isset($depinfo["verify_opts"]))  $cmd .= " " . $depinfo["verify_opts"];

		$errorfilename = $rootpath . "/temp/logs/verify_dependency_" . microtime(true) . "_error.log";

		$result = RunCommand($cmd, $errorfilename, NULL, $tempenv);

		// Emitting errors isn't necessarily a problem (yet).
		$errors = file_get_contents($errorfilename);
		unlink($errorfilename);

		if ($result === false)
		{
			CLI::DisplayError("Process failed to start.  Attempted to run:  " . $cmd, false, false);

			return false;
		}

		$result .= "\n" . $errors;

		if ((isset($depinfo["required_output"]) && $depinfo["required_output"] === "") || (isset($depinfo["preferred_output"]) && $depinfo["preferred_output"] === ""))
		{
			echo $result . "\n";

			CLI::DisplayError("Required or preferred output are empty strings.");
		}

		// Check output for required/preferred strings.
		$foundreq = (!isset($depinfo["required_output"]));
		$foundpref = false;
		$lines = explode("\n", $result);
		foreach ($lines as $line)
		{
			if (isset($depinfo["required_output"]) && preg_match($depinfo["required_output"], $line))  $foundreq = true;
			if (isset($depinfo["preferred_output"]) && preg_match($depinfo["preferred_output"], $line))  $foundpref = true;
		}

		if (!$foundreq)
		{
			if ($errors !== "")  CLI::DisplayError("Attempted command:  ". $cmd . "\nExecutable emitted errors:\n" . $errors, false, false);

			CLI::DisplayError("Required output not returned.  " . $depinfo["required_alert"], false, false);

			return false;
		}

		if (!$foundpref && isset($depinfo["preferred_output"]))
		{
			if ($errors !== "")  CLI::DisplayError("Attempted command:  ". $cmd . "\nExecutable emitted errors:\n" . $errors, false, false);

			CLI::DisplayError("Preferred output not returned.  " . $depinfo["preferred_alert"], false, false);

			if ($failpreferred)  return false;
		}

		return true;
	}

	// Downloads a file to /temp and extracts/installs it to its target location (e.g. /versions/X.X/deps).
	function DownloadTempFileAndExtract($pathmap, $downloadinfo, $downloadkey)
	{
		global $rootpath, $suppressoutput;

		// Check to see if already downloaded and extracted.
		$installedfilename = $pathmap["[[DEPS_DIR]]"] . "/installed.json";
		$installed = @json_decode(file_get_contents($installedfilename), true);
		if (!is_array($installed))  $installed = array();

		if (!isset($downloadinfo["download_extract_path"]))  return;

		$extractpath = str_replace(array_keys($pathmap), array_values($pathmap), $downloadinfo["download_extract_path"]);

		if (!isset($installed[$extractpath]) || $installed[$extractpath] !== $downloadinfo[$downloadkey] || !is_dir($extractpath) || !VerifyDependency($pathmap, $downloadinfo, true))
		{
			// Download and verify the file.
			DownloadTempFile($pathmap, $downloadinfo, $downloadkey);

			// Delete existing installation (if any).
			DeleteDirectory($extractpath);

			// Extract the downloaded and verified file.
			if (isset($downloadinfo[$downloadkey . "_temp"]))  $tempfile = $downloadinfo[$downloadkey . "_temp"];
			else
			{
				$url = str_replace(array_keys($pathmap), array_values($pathmap), $downloadinfo[$downloadkey]);

				$pos = strrpos($url, "/");
				$tempfile = substr($url, $pos + 1);
			}

			$tempfilename = $rootpath . "/temp/" . $tempfile;

			switch ($downloadinfo["download_type"])
			{
				case "tar.gz":
				{
					@mkdir($extractpath, 0775, true);

					if (!$suppressoutput)  echo "Extracting '" . $tempfilename . "' to '" . $extractpath . "'...\n";

					try
					{
						$phar = new PharData($tempfilename);
					}
					catch (Exception $e)
					{
						CLI::DisplayError("Unable to open tar.gz archive '" . $tempfilename . "'.  " . $e->getMessage());
					}

					try
					{
						$phar->extractTo($extractpath);
					}
					catch (Exception $e)
					{
						CLI::DisplayError("Failed to extract '" . $tempfilename . "'.  " . $e->getMessage());
					}

					unset($phar);

					break;
				}
				case "zip":
				{
					@mkdir($extractpath, 0775, true);

					if (!$suppressoutput)  echo "Extracting '" . $tempfilename . "' to '" . $extractpath . "'...\n";

					$zip = new ZipArchive;
					if (!$zip->open($tempfilename, ZipArchive::RDONLY))  CLI::DisplayError("Unable to open ZIP archive '" . $tempfilename . "'.");
					if (!$zip->extractTo($extractpath))  CLI::DisplayError("Failed to extract '" . $tempfilename . "'.");
					$zip->close();

					break;
				}
				case "exe":
				{
					if (!$suppressoutput)  echo "Installing '" . $tempfilename . "' to '" . $extractpath . "'...\n";

					$opts = $downloadinfo["download_install_opts"];
					foreach ($pathmap as $key => $val)  $opts = str_replace($key, str_replace("/", "\\", $val), $opts);

					$cmd = escapeshellarg(str_replace("/", "\\", $tempfilename)) . " " . $opts;

					$errorfilename = $rootpath . "/temp/logs/install_exe_" . microtime(true) . "_error.log";

					$result = RunCommand($cmd, $errorfilename);

					$errors = file_get_contents($errorfilename);
					unlink($errorfilename);

					if ($result === false)  CLI::DisplayError("An error occurred while attempting to run '" . $cmd . "'.");

					if (!$suppressoutput)  echo $result;

					if ($errors !== "")  CLI::DisplayError("Executable emitted errors:\n" . $errors);

					break;
				}
				default:
				{
					CLI::DisplayError("Unknown download type '" . $downloadtype . "'.");
				}
			}

			if (!VerifyDependency($pathmap, $downloadinfo, true))  CLI::DisplayError("Unable to verify correct setup of the dependency.");

			// Update installed dependencies.
			$installed[$extractpath] = $downloadinfo[$downloadkey];

			file_put_contents($installedfilename, json_encode($installed, JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT));
		}
	}

	if ($cmd === "init")
	{
		// Initialize a base version.  Sets up directory structure and then downloads and extracts/installs dependencies.
		$versions = GetBaseVersions();

		$basever = CLI::GetLimitedUserInputWithArgs($args, "version", "Version", false, "Available versions:", $versions, true, $suppressoutput);

		$verdata = LoadAndExpandBaseVersionInfo($basever);

		// Determine current system capabilities (prefer x64 if possible).
		$downloadpref = (PHP_INT_SIZE >= 8 ? "download_x64" : "download_x86");

		// Download, verify, and extract dependencies.
		@mkdir($rootpath . "/versions/" . $basever . "/deps", 0775, true);

		$pathmap = array(
			"[[ROOTPATH]]" => $rootpath,
			"[[BASE_VERSION_DIR]]" => $rootpath . "/versions/" . $basever,
			"[[DEPS_DIR]]" => $rootpath . "/versions/" . $basever . "/deps"
		);

		foreach ($verdata["architectures"] as $archinfo)
		{
			foreach ($archinfo["dependencies"] as $depinfo)
			{
				if (isset($depinfo[$downloadpref]))  DownloadTempFileAndExtract($pathmap, $depinfo, $downloadpref);
				else if (isset($depinfo["download"]))  DownloadTempFileAndExtract($pathmap, $depinfo, "download");
			}
		}

		CLI::DisplayResult(array("success" => true, "path" => $pathmap["[[BASE_VERSION_DIR]]"]));
	}
	else if ($cmd === "init-test")
	{
		// Test the downloads and verify hashes.  Should be run when updating dependencies.
		CLI::ReinitArgs($args, array("version"));

		$versions = GetBaseVersions();

		$basever = CLI::GetLimitedUserInputWithArgs($args, "version", "Version", false, "Available versions:", $versions, true, $suppressoutput);

		$verdata = LoadAndExpandBaseVersionInfo($basever);

		$pathmap = array();

		foreach ($verdata["architectures"] as $archinfo)
		{
			foreach ($archinfo["dependencies"] as $depinfo)
			{
				if (isset($depinfo["download_x86"]))  DownloadTempFile($pathmap, $depinfo, "download_x86");
				if (isset($depinfo["download_x64"]))  DownloadTempFile($pathmap, $depinfo, "download_x64");
				if (isset($depinfo["download"]))  DownloadTempFile($pathmap, $depinfo, "download");
			}
		}

		CLI::DisplayResult(array("success" => true));
	}
	else if ($cmd === "save-profile")
	{
		// Validate and save an environment profile for a specific base version and architecture.
		CLI::ReinitArgs($args, array("version", "arch"));

		$versions = GetBaseVersions();

		$basever = CLI::GetLimitedUserInputWithArgs($args, "version", "Version", false, "Available versions:", $versions, true, $suppressoutput);

		// Load the base version.
		$verdata = LoadAndExpandBaseVersionInfo($basever);

		// Get available architectures.
		$archs = array();

		foreach ($verdata["architectures"] as $archinfo)
		{
			if (isset($archinfo["build"]))  $archs[$archinfo["architecture"]] = $archinfo["name"];
		}

		$arch = CLI::GetLimitedUserInputWithArgs($args, "arch", "Architecture", false, "Available architectures:", $archs, true, $suppressoutput);

		$pathmap = array(
			"[[ROOTPATH]]" => $rootpath,
			"[[BASE_VERSION_DIR]]" => $rootpath . "/versions/" . $basever,
			"[[DEPS_DIR]]" => $rootpath . "/versions/" . $basever . "/deps"
		);

		// Verify dependencies for the selected architecture.
		foreach ($verdata["architectures"] as $archinfo)
		{
			if ($archinfo["architecture"] === $arch)
			{
				foreach ($archinfo["dependencies"] as $depinfo)
				{
					if (!VerifyDependency($pathmap, $depinfo, false))  CLI::DisplayError("Dependency verification failed for '" . $depinfo["name"] . "'.");
				}
			}
		}

		// Save the environment profile.
		$tempenv = GetCleanEnvironment();

		$profilepath = $rootpath . "/versions/" . $basever . "/profiles";

		@mkdir($profilepath, 0775, true);

		file_put_contents($profilepath . "/" . $arch . ".json", json_encode($tempenv, JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT));

		CLI::DisplayResult(array("success" => true, "profile" => $profilepath . "/" . $arch . ".json"));
	}
	else if ($cmd === "prepare")
	{
		// Download a source tarball for a specific version, verify and extract, and generate versioned installer scripts.
		CLI::ReinitArgs($args, array("version"));

		$result = GetSpecificVersionInput("Enter the version of OpenSSL to download.  Must be a release version of a supported base version.");

		$basever = $result["basever"];
		$ver = $result["ver"];

		// Load the base version.
		$verdata = LoadAndExpandBaseVersionInfo($basever);

		// Download the OpenSSL source tarball, verify, and extract.
		$pathmap = array(
			"[[ROOTPATH]]" => $rootpath,
			"[[BASE_VERSION_DIR]]" => $rootpath . "/versions/" . $basever,
			"[[DEPS_DIR]]" => $rootpath . "/versions/" . $basever . "/deps",
			"[[VERSION_DIR]]" => $rootpath . "/versions/" . $basever . "/" . $ver,
			"[[DOTTED_VERSION]]" => $ver,
			"[[WINDOWS_DOTTED_VERSION]]" => implode(".", array_slice(explode(".", preg_replace('/[^0-9.]/', "", $ver)), 0, 4)),
			"[[MSI_DOTTED_VERSION]]" => implode(".", array_slice(explode(".", preg_replace('/[^0-9.]/', "", $ver)), 0, 3)),
			"[[UNDERSCORE_VERSION]]" => str_replace(".", "_", $ver),
			"[[HYPHEN_VERSION]]" => str_replace(".", "-", $ver),
		);

		DownloadTempFileAndExtract($pathmap, $verdata, "download");

		// Generate versioned installer scripts from the templates.
		@mkdir($pathmap["[[VERSION_DIR]]"] . "/installers", 0775, true);

		foreach ($verdata["architectures"] as $archinfo)
		{
			$path = $rootpath . "/templates/" . $basever . "/" . $archinfo["architecture"];

			$dir = opendir($path);
			if (!$dir)  CLI::DisplayError("Unable to open directory '" . $path . "'.");

			while (($file = readdir($dir)) !== false)
			{
				if ($file !== "." && $file !== ".." && is_file($path . "/" . $file))
				{
					$data = file_get_contents($path . "/" . $file);
					if ($data !== false)
					{
						$pathmap["[[INSTALLER_SCRIPT_DIR]]"] = $pathmap["[[VERSION_DIR]]"] . "/installers/" . $archinfo["architecture"];
						$pathmap["[[INSTALLER_SOURCE_DIR]]"] = $pathmap["[[INSTALLER_SCRIPT_DIR]]"] . "/final";

						foreach ($pathmap as $key => $val)  $data = str_replace($key, str_replace("/", "\\", $val), $data);

						@mkdir($pathmap["[[INSTALLER_SCRIPT_DIR]]"], 0775, true);

						file_put_contents($pathmap["[[INSTALLER_SCRIPT_DIR]]"] . "/" . $file, $data);
					}
				}
			}
		}

		CLI::DisplayResult(array("success" => true));
	}
	else if ($cmd === "build-all")
	{
		// Build all architectures for all specific versions.
		CLI::ReinitArgs($args, array("version"));

		$specificvers = array();

		do
		{
			$result = GetSpecificVersionInput("Enter the version of OpenSSL to build.  Must be a prepared version.");

			$basever = $result["basever"];
			$ver = $result["ver"];

			if (!is_dir($rootpath . "/versions/" . $basever . "/" . $ver . "/installers"))  CLI::DisplayError("The entered version (" . $ver . ") does not exist or is not prepared correctly.");

			// Load the base version.
			$verdata = LoadAndExpandBaseVersionInfo($basever);

			$profiles = GetProfileList($basever, $verdata);

			if (!count($profiles))  CLI::DisplayError("No environment profiles have been defined for " . $ver . ".  See README.md on how to configure environment profiles.");

			$specificvers[$ver] = array("basever" => $basever, "verdata" => $verdata, "profiles" => $profiles);
		} while ((isset($args["opts"]["version"]) && count($args["opts"]["version"])) || count($args["params"]));

		// Start a process for each specific version and architecture.
		$procs = array();
		foreach ($specificvers as $ver => $verinfo)
		{
			foreach ($verinfo["profiles"] as $arch => $name)
			{
				$cmd = escapeshellarg(PHP_BINARY) . " " . escapeshellarg(__FILE__) . " -suppressoutput build " . escapeshellarg($ver) . " " . escapeshellarg($arch);

				if (!$suppressoutput)  echo "Starting '" . $cmd . "'...\n";

				$os = php_uname("s");
				$windows = (strtoupper(substr($os, 0, 3)) == "WIN");

				$descriptors = array(
					0 => array("file", ($windows ? "NUL" : "/dev/null"), "r"),
					1 => array("socket", "w"),
					2 => array("socket", "w")
				);

				$proc = @proc_open($cmd, $descriptors, $pipes, NULL, NULL, array("suppress_errors" => true, "bypass_shell" => true));

				if (!is_resource($proc) || !isset($pipes[1]))  CLI::DisplayError("Failed to start process.");

				if (isset($pipes[0]))
				{
					@fclose($pipes[0]);

					unset($pipes[0]);
				}

				foreach ($pipes as $fp)  stream_set_blocking($fp, 0);

				$procs[] = array("proc" => $proc, "pipes" => $pipes);
			}
		}

		// Wait for all processes to finish running.
		while (count($procs))
		{
			$readfps = array();
			foreach ($procs as $num => $procinfo)
			{
				foreach ($procinfo["pipes"] as $fp)  $readfps[] = $fp;
			}

			$writefps = array();
			$exceptfps = NULL;
			$result = @stream_select($readfps, $writefps, $exceptfps, 3);
			if ($result === false)  CLI::DisplayError("A stream_select() call failed.");

			foreach ($readfps as $readfp)
			{
				foreach ($procs as $num => $procinfo)
				{
					foreach ($procinfo["pipes"] as $pnum => $fp)
					{
						if ($readfp === $fp)
						{
							echo @fgets($fp);

							if (feof($fp))
							{
								fclose($fp);

								unset($procs[$num]["pipes"][$pnum]);
							}
						}
					}

					if (!count($procs[$num]["pipes"]))
					{
						@proc_close($procinfo["proc"]);

						unset($procs[$num]);
					}
				}
			}
		}

		// Copies a directory tree into a ZIP archive.
		function CopyDirectoryToZIPFile($zipfilename, $zip, &$size, $srcpath, $destpath)
		{
			global $suppressoutput;

			$dir = opendir($srcpath);
			if (!$dir)  CLI::DisplayError("Failed to open directory '" . $srcpath . "' for reading.");

			if (!$zip->addEmptyDir($destpath))  CLI::DisplayError("Failed to create '" . $destpath . "' in '" . $zipfilename . "'.");

			while (($file = readdir($dir)) !== false)
			{
				if ($file !== "." && $file !== "..")
				{
					if (is_dir($srcpath . "/" . $file))  CopyDirectoryToZIPFile($zipfilename, $zip, $size, $srcpath . "/" . $file, $destpath . "/" . $file);
					else if (is_file($srcpath . "/" . $file))
					{
						if (!$zip->addFile($srcpath . "/" . $file, $destpath . "/" . $file))  CLI::DisplayError("Failed to add file '" . $srcpath . "/" . $file . "' as '" . $destpath . "/" . $file . "' in '" . $zipfilename . "'.");
						else
						{
							$size += filesize($srcpath . "/" . $file);

							if ($size > 1024768)
							{
								// Flush data to disk.
								if (!$suppressoutput)  echo ".";

								if (!$zip->close())  CLI::DisplayError("Failed to write to '" . $zipfilename . "'.");
								if (!$zip->open($zipfilename))  CLI::DisplayError("Failed to reopen '" . $zipfilename . "'.");

								while ($size > 1024768)  $size -= 1024768;
							}
						}
					}
				}
			}

			closedir($dir);
		}

		// Creates a ZIP file out of a directory tree.
		function CreateZIPFile($zipfilename, $srcpath, $destpath)
		{
			global $suppressoutput;

			if (!$suppressoutput)  echo "Creating '" . $zipfilename . "'...";

			@unlink($zipfilename);

			$zip = new ZipArchive;
			if (!$zip->open($zipfilename, ZipArchive::CREATE | ZipArchive::EXCL))  CLI::DisplayError("Failed to create '" . $zipfilename . "'.");

			$size = 0;
			CopyDirectoryToZIPFile($zipfilename, $zip, $size, $srcpath, $destpath);

			if (!$zip->close())  CLI::DisplayError("Failed to write to '" . $zipfilename . "'.");

			echo "\n";
		}

		// Construct a portable edition for each version.
		foreach ($specificvers as $ver => $verinfo)
		{
			if (!$suppressoutput)  echo "Generating portable edition for " . $ver . "...\n";

			$basever = $verinfo["basever"];
			$verdata = $verinfo["verdata"];

			$pathmap = array(
				"[[ROOTPATH]]" => $rootpath,
				"[[BASE_VERSION_DIR]]" => $rootpath . "/versions/" . $basever,
				"[[VERSION_DIR]]" => $rootpath . "/versions/" . $basever . "/" . $ver,
				"[[INSTALLERS_DIR]]" => $rootpath . "/versions/" . $basever . "/" . $ver . "/installers"
			);

			// Remove previous build.
			DeleteDirectory($pathmap["[[INSTALLERS_DIR]]"] . "/portable");

			$destdir = $pathmap["[[INSTALLERS_DIR]]"] . "/portable/final";

			// Copy executable files from generated installer directories.
			$first = true;

			foreach ($verinfo["profiles"] as $arch => $name)
			{
				$srcdir = $pathmap["[[INSTALLERS_DIR]]"] . "/" . $arch . "/final";

				if (!is_dir($srcdir))  CLI::DisplayError("Directory does not exist '" . $srcdir . "'.  Build failed.");

				if ($first)
				{
					CopyFiles($srcdir . "/conf", $destdir . "/conf", true);
					CopyFiles($srcdir . "/text", $destdir . "/text", true);
					CopyFiles($srcdir . "/tools", $destdir . "/tools", true);

					$first = false;
				}

				CopyFiles($srcdir . "/bin", $destdir . "/bin/" . $arch, true);
				CopyFiles($srcdir . "/bin_static", $destdir . "/bin_static/" . $arch, true);

				$data = file_get_contents($srcdir . "/start.bat");
				$data = str_replace("dp0bin", "dp0bin\\" . $arch, $data);
				file_put_contents($destdir . "/start_" . $arch . ".bat", $data);
			}

			// Prepare light ZIP file with executables/DLLs only.
			CreateZIPFile($pathmap["[[INSTALLERS_DIR]]"] . "/portable/OpenSSL-" . $ver . "-win-portable.zip", $destdir, "openssl-" . $ver);

			// Copy developer files from generated installer directories.
			foreach ($verinfo["profiles"] as $arch => $name)
			{
				$srcdir = $pathmap["[[INSTALLERS_DIR]]"] . "/" . $arch . "/final";

				CopyFiles($srcdir . "/include", $destdir . "/include/" . $arch, true);
				CopyFiles($srcdir . "/exp", $destdir . "/exp/" . $arch, true);
				CopyFiles($srcdir . "/lib", $destdir . "/lib/", true);
			}

			// Prepare ZIP file with developer libraries.
			CreateZIPFile($pathmap["[[INSTALLERS_DIR]]"] . "/portable/OpenSSL-" . $ver . "-win-portable-dev.zip", $destdir, "openssl-" . $ver . "-dev");
		}

		CLI::DisplayResult(array("success" => true));
	}
	else if ($cmd === "build")
	{
		// Build a specific version and architecture.
		CLI::ReinitArgs($args, array("version", "arch"));

		$result = GetSpecificVersionInput("Enter the version of OpenSSL to build.  Must be a prepared version.");

		$basever = $result["basever"];
		$ver = $result["ver"];

		if (!is_dir($rootpath . "/versions/" . $basever . "/" . $ver . "/installers"))  CLI::DisplayError("The entered version (" . $ver . ") does not exist or is not prepared correctly.");

		// Load the base version.
		$verdata = LoadAndExpandBaseVersionInfo($basever);

		$profiles = GetProfileList($basever, $verdata);

		if (!count($profiles))  CLI::DisplayError("No environment profiles have been defined.  See README.md on how to configure environment profiles.");

		$arch = CLI::GetLimitedUserInputWithArgs($args, "arch", "Architecture", false, "Available architectures to build:", $profiles, true, $suppressoutput);

		$echoprefix = "[" . $ver . "; " . $arch . "]";

		// Load the environment profile.
		$filename = $rootpath . "/versions/" . $basever . "/profiles/" . $arch . ".json";
		$baseenv = json_decode(file_get_contents($filename), true);
		if (!is_array($baseenv))  CLI::DisplayError($echoprefix . " Saved environment profile '" . $filename . "' is not valid.");

		// Apply all dependency environment modifications.
		$pathmap = array(
			"[[ROOTPATH]]" => $rootpath,
			"[[BASE_VERSION_DIR]]" => $rootpath . "/versions/" . $basever,
			"[[DEPS_DIR]]" => $rootpath . "/versions/" . $basever . "/deps",
			"[[VERSION_DIR]]" => $rootpath . "/versions/" . $basever . "/" . $ver,
			"[[SOURCE_ORIG_DIR]]" => $rootpath . "/versions/" . $basever . "/" . $ver . "/source/openssl-" . $ver,
			"[[SOURCE_TEMP_DIR]]" => $rootpath . "/versions/" . $basever . "/" . $ver . "/temp_" . $arch,
			"[[BUILD_OUTPUT_DIR]]" => $rootpath . "/versions/" . $basever . "/" . $ver . "/out_" . $arch,
			"[[INSTALLERS_DIR]]" => $rootpath . "/versions/" . $basever . "/" . $ver . "/installers",
			"[[INSTALLERS_ARCH_DIR]]" => $rootpath . "/versions/" . $basever . "/" . $ver . "/installers/" . $arch,
		);

		$baseenvkeymap = GetEnvironmentKeymap($baseenv);

		foreach ($verdata["architectures"] as $archinfo)
		{
			if ($archinfo["architecture"] === $arch)
			{
				if (!isset($archinfo["build"]))  CLI::DisplayError($echoprefix . " Unable to build due to missing 'build' information in the JSON data.");

				foreach ($archinfo["dependencies"] as $depinfo)
				{
					ApplyDependencyEnvironment($baseenv, $baseenvkeymap, $pathmap, $depinfo);
				}

				break;
			}
		}

		$startts = time();

		// Clean up previous/failed builds.
		echo $echoprefix . " Cleaning up previous builds...\n";
		DeleteDirectory($pathmap["[[SOURCE_TEMP_DIR]]"]);
		DeleteDirectory($pathmap["[[INSTALLERS_ARCH_DIR]]"] . "/final");

		@mkdir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs", 0775, true);

		// Specialty recursive file copy to ignore certain file extensions in the build tree.
		function CopyBuildFiles($srcdir, $destdir, $path, $recurse, $pattern = "/.*/")
		{
			$srcpath = $srcdir . "/" . $path;

			$excludeexts = array(
				".c" => true,
				".d" => true,
				".ec" => true,
				".h" => true,
				".obj" => true,
				".ilk" => true,
				".pdb" => true,  // While PDB files might be ideal for debug builds, the generated files are about 8 times larger than the DLLs and include local system and build path strings.
				".in" => true,
				".info" => true,
				".md" => true,
				".asm" => true,
				".mar" => true,
			);

			if (!is_dir($srcpath))  return;

			$dir = opendir($srcpath);
			if ($dir)
			{
				while (($file = readdir($dir)) !== false)
				{
					if ($file !== "." && $file !== "..")
					{
						if (is_dir($srcpath . "/" . $file))
						{
							if ($recurse)  CopyBuildFiles($srcpath, $destdir . "/" . $path, $file, true, $pattern);
						}
						else if (strpos($file, ".") !== false && !isset($excludeexts[substr($file, strrpos($file, "."))]) && preg_match($pattern, $file))
						{
							@mkdir($destdir . "/" . $path, 0777, true);

							copy($srcpath . "/" . $file, $destdir . "/" . $path . "/" . $file);
						}
					}
				}

				closedir($dir);
			}
		}

		// Builds OpenSSL.
		function RunBuild($ver, $arch, $baseenv, $buildnum, $pathmap, $archinfo, $configuretype, $buildtype, $outdir, $copymodes)
		{
			$echoprefix = "[" . $ver . "; " . $arch . "; Build " . $buildnum . "; " . $outdir . "]";

			echo $echoprefix . " Started build at " . date("Y-m-d H:i:s") . ".\n";
			$ts = time();

			DeleteDirectory($pathmap["[[SOURCE_TEMP_DIR]]"]);

			// Clone the source tree to the temporary architecture directory.
			// Doing this allows multiple architectures for a base version to be built simultaneously.
			echo $echoprefix . " Cloning source tree...\n";
			CopyDirectory($pathmap["[[SOURCE_ORIG_DIR]]"], $pathmap["[[SOURCE_TEMP_DIR]]"]);


			// Run perl Configure.
			$cmd = escapeshellarg("perl.exe") . " Configure " . $archinfo["build"]["configure_target"] . " " . $configuretype . " " . $archinfo["build"]["configure_extra"];
			echo $echoprefix . " Running '" . $cmd . "'...\n";

			$errorfilename = $pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/" . $buildnum . "_perl_configure_" . $outdir . "_error.log";
			$result = RunCommand($cmd, $errorfilename, $pathmap["[[SOURCE_TEMP_DIR]]"], $baseenv);
			if ($result === false)  CLI::DisplayError($echoprefix . " Failed to start process.");

			file_put_contents($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/" . $buildnum . "_perl_configure_" . $outdir . "_out.log", $result);

			if (!file_exists($pathmap["[[SOURCE_TEMP_DIR]]"] . "/makefile"))  CLI::DisplayError($echoprefix . " Failed to generate 'makefile'.");


			// Nothing is perfect.  Patch the makefile.
			$data = file_get_contents($pathmap["[[SOURCE_TEMP_DIR]]"] . "/makefile");

			foreach ($archinfo["build"]["patches"] as $key => $val)
			{
				$data = str_replace($key, $val, $data);
			}

			// The 'no-shared' build should only generate statically linked libraries and executables.
			if (strpos($configuretype, "no-shared") !== false)
			{
				$data = str_replace("MODULES=providers\\legacy.dll", "MODULES=", $data);
				$data = str_replace("MODULEPDBS=providers\\legacy.pdb", "MODULEPDBS=", $data);
			}

			// Fix the build type.
			$data = str_replace(" /MTd ", " " . $buildtype . " ", $data);
			$data = str_replace(" /MTd\r\n", " " . $buildtype . "\r\n", $data);
			$data = str_replace(" /MT ", " " . $buildtype . " ", $data);
			$data = str_replace(" /MT\r\n", " " . $buildtype . "\r\n", $data);

			$data = str_replace(" /MDd ", " " . $buildtype . " ", $data);
			$data = str_replace(" /MDd\r\n", " " . $buildtype . "\r\n", $data);
			$data = str_replace(" /MD ", " " . $buildtype . " ", $data);
			$data = str_replace(" /MD\r\n", " " . $buildtype . "\r\n", $data);

			file_put_contents($pathmap["[[SOURCE_TEMP_DIR]]"] . "/makefile", $data);


			// Run nmake.
			$cmd = escapeshellarg("nmake.exe") . " -f makefile";
			echo $echoprefix . " Running '" . $cmd . "'...\n";

			$errorfilename = $pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/" . $buildnum . "_nmake_" . $outdir . "_error.log";
			$result = RunCommand($cmd, $errorfilename, $pathmap["[[SOURCE_TEMP_DIR]]"], $baseenv);
			if ($result === false)  CLI::DisplayError($echoprefix . " Failed to start process.");

			file_put_contents($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/" . $buildnum . "_nmake_" . $outdir . "_out.log", $result);

			if (!file_exists($pathmap["[[SOURCE_TEMP_DIR]]"] . "/apps/openssl.exe"))  CLI::DisplayError($echoprefix . " Failed to generate 'apps/openssl.exe'.");


			// Copy files to the build output directory.
			$indir = $pathmap["[[SOURCE_TEMP_DIR]]"];
			$outdir2 = $pathmap["[[BUILD_OUTPUT_DIR]]"] . "/" . $outdir;
			@mkdir($outdir2, 0775, true);
			if (in_array("all", $copymodes) || in_array("apps", $copymodes))  CopyBuildFiles($indir, $outdir2, "apps", true);
			if (in_array("all", $copymodes) || in_array("engines", $copymodes))  CopyBuildFiles($indir, $outdir2, "engines", false);
			if (in_array("all", $copymodes) || in_array("fuzz", $copymodes))  CopyBuildFiles($indir, $outdir2, "fuzz", false);
			if (in_array("all", $copymodes) || in_array("providers", $copymodes))  CopyBuildFiles($indir, $outdir2, "providers", false);
			if (in_array("all", $copymodes) || in_array("test", $copymodes))  CopyBuildFiles($indir, $outdir2, "test", true);
			if (in_array("all", $copymodes) || in_array("tools", $copymodes))  CopyBuildFiles($indir, $outdir2, "tools", true);

			CopyBuildFiles($indir, $outdir2, "", false, '/(\.exp|\.lib|\.def|\.dll|\.pdb)$/');


			// Build comleted.
			$ts2 = time();
			$secs = $ts2 - $ts;
			$mins = (int)($secs / 60);
			$secs %= 60;

			echo $echoprefix . " Finished build at " . date("Y-m-d H:i:s") . ".  Build time:  " . $mins . " min " . $secs . " sec\n";
		}

		// Run first build.  This build takes much longer due to also building the test suite.
		if (!is_dir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD") || !is_dir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/inc"))
		{
			RunBuild($ver, $arch, $baseenv, 1, $pathmap, $archinfo, "shared", "/MD", "dll_MD", array("all"));

			// Copy the include files.
			@mkdir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/inc/openssl", 0775, true);
			$dir = opendir($pathmap["[[SOURCE_TEMP_DIR]]"] . "/include/openssl");
			if ($dir)
			{
				while (($file = readdir($dir)) !== false)
				{
					if (strtolower(substr($file, -2)) === ".h")
					{
						// Convert line endings to DOS line endings.
						$data = file_get_contents($pathmap["[[SOURCE_TEMP_DIR]]"] . "/include/openssl/" . $file);

						$data = str_replace("\r\n", "\n", $data);
						$data = str_replace("\r", "\n", $data);
						$data = str_replace("\n", "\r\n", $data);

						file_put_contents($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/inc/openssl/" . $file, $data);
					}
				}

				closedir($dir);
			}

			// Copy ms/applink.c too.
			// Convert line endings to DOS line endings.
			$data = file_get_contents($pathmap["[[SOURCE_TEMP_DIR]]"] . "/ms/applink.c");

			$data = str_replace("\r\n", "\n", $data);
			$data = str_replace("\r", "\n", $data);
			$data = str_replace("\n", "\r\n", $data);

			file_put_contents($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/inc/openssl/applink.c", $data);
		}

		// Run the remaining builds.
		if (!is_dir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MT"))  RunBuild($ver, $arch, $baseenv, 2, $pathmap, $archinfo, "shared no-tests", "/MT", "dll_MT", array("apps"));
		if (!is_dir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MDd"))  RunBuild($ver, $arch, $baseenv, 3, $pathmap, $archinfo, "--debug shared no-tests", "/MDd", "dll_MDd", array());
		if (!is_dir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MTd"))  RunBuild($ver, $arch, $baseenv, 4, $pathmap, $archinfo, "--debug shared no-tests", "/MTd", "dll_MTd", array());

		if (!is_dir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/static_MD"))  RunBuild($ver, $arch, $baseenv, 5, $pathmap, $archinfo, "no-shared no-tests", "/MD", "static_MD", array("apps"));
		if (!is_dir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/static_MT"))  RunBuild($ver, $arch, $baseenv, 6, $pathmap, $archinfo, "no-shared no-tests", "/MT", "static_MT", array("apps"));
//		if (!is_dir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/static_MDd"))  RunBuild($ver, $arch, $baseenv, 7, $pathmap, $archinfo, "--debug no-shared no-tests", "/MDd", "static_MDd", array());
//		if (!is_dir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/static_MTd"))  RunBuild($ver, $arch, $baseenv, 8, $pathmap, $archinfo, "--debug no-shared no-tests", "/MTd", "static_MTd", array());

		// Remove the temporary build directory.
		DeleteDirectory($pathmap["[[SOURCE_TEMP_DIR]]"]);

		// Prepare installation directory and run installers.
		if (is_dir($pathmap["[[INSTALLERS_ARCH_DIR]]"]))
		{
			if (!isset($archinfo["package"]))  CLI::DisplayError($echoprefix . " Unable to package the build due to missing 'package' information in the JSON data.");

			echo $echoprefix . " Started packaging at " . date("Y-m-d H:i:s") . ".\n";

			$destdir = $pathmap["[[INSTALLERS_ARCH_DIR]]"] . "/final";

			echo $echoprefix . " Copying files to '" . $destdir . "'...\n";

			@mkdir($destdir, 0775, true);

			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD", $destdir, false, '/(\.dll)$/');
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD", $destdir . "/bin", true, '/(\.dll)$/', true);
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD", $destdir . "/exp", true, '/(\.exp)$/', true);

			// VC++ libraries.
			$libdir = $destdir . "/lib/VC/" . $arch;
			@mkdir($libdir . "/static", 0775, true);
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD", $libdir . "/MD", true, '/(\.lib|\.def)$/', true);
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MDd", $libdir . "/MDd", false, '/(\.lib|\.def)$/');
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MT", $libdir . "/MT", false, '/(\.lib|\.def)$/');
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MTd", $libdir . "/MTd", false, '/(\.lib|\.def)$/');

			// OpenSSL.exe.
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/apps", $destdir . "/bin", false, '/(\.exe)$/');
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/static_MT/apps", $destdir . "/bin_static", false, '/(\.exe)$/');

			// Configurations.
			copy($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/apps/openssl.cnf", $destdir . "/bin/openssl.cfg");  // This is very old and is a long story.
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/apps", $destdir . "/bin/cnf", false, '/(\.cnf)$/');
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/apps", $destdir . "/conf", false, '/(\.cnf)$/');

			// Perl scripts.
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/apps", $destdir . "/bin", false, '/(\.pl)$/');
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/tools", $destdir . "/tools", true);

			// Test suites.
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/test", $destdir . "/tests", true);
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD", $destdir . "/tests", false, '/(\.dll)$/');
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/fuzz", $destdir . "/tests/fuzz", true);
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD", $destdir . "/tests/fuzz", false, '/(\.dll)$/');

			// PEM files.
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/apps", $destdir . "/bin/PEM", false, '/(\.pem|\.srl)$/');
			if (is_dir($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/apps/demoCA"))  CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/apps/demoCA", $destdir . "/bin/PEM/demoCA", true);
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD/apps/demoSRP", $destdir . "/bin/PEM/demoSRP", true);

			// Includes.
			CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/inc", $destdir . "/include", true);

			// Text files.
			@mkdir($destdir . "/text", 0775, true);
			CopyTextFile($pathmap["[[SOURCE_ORIG_DIR]]"] . "/ACKNOWLEDGEMENTS", $destdir . "/text/acknowledgements.txt");
			CopyTextFile($pathmap["[[SOURCE_ORIG_DIR]]"] . "/AUTHORS", $destdir . "/text/authors.txt");
			CopyTextFile($pathmap["[[SOURCE_ORIG_DIR]]"] . "/CHANGES", $destdir . "/text/changes.txt");
			CopyTextFile($pathmap["[[SOURCE_ORIG_DIR]]"] . "/FAQ", $destdir . "/text/faq.txt");
			CopyTextFile($pathmap["[[SOURCE_ORIG_DIR]]"] . "/LICENSE", $destdir . "/text/license.txt");
			CopyTextFile($pathmap["[[SOURCE_ORIG_DIR]]"] . "/NEWS", $destdir . "/text/news.txt");
			CopyTextFile($pathmap["[[SOURCE_ORIG_DIR]]"] . "/README", $destdir . "/text/readme.txt");

			CopyTextFile($pathmap["[[SOURCE_ORIG_DIR]]"] . "/LICENSE", $destdir . "/license.txt");

			// Start menu batch file.
			if (file_exists($pathmap["[[INSTALLERS_ARCH_DIR]]"] . "/start.bat"))  copy($pathmap["[[INSTALLERS_ARCH_DIR]]"] . "/start.bat", $destdir . "/start.bat");

			// MinGW libraries.
			if (isset($archinfo["package"]["mingw_dlltool"]) && $archinfo["package"]["mingw_dlltool"] !== "")
			{
				echo $echoprefix . " Generating MinGW libraries...\n";

				$mingwlibdir = $destdir . "/lib/MinGW/" . $arch;

				CopyFiles($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/dll_MD", $mingwlibdir, false, '/(\.def)$/');

				$dir = opendir($mingwlibdir);
				if ($dir)
				{
					while (($file = readdir($dir)) !== false)
					{
						if (substr($file, -4) === ".def")
						{
							$cmd = str_replace(array_keys($pathmap), array_values($pathmap), $archinfo["package"]["mingw_dlltool"]);
							$cmd = escapeshellarg(str_replace("/", "\\", $cmd));

							$cmd .= " --def .\\lib\\MinGW\\" . $arch . "\\" . $file . " --dllname " . substr($file, 0, -4) . ".dll --output-lib .\\lib\\MinGW\\" . $arch . "\\" . substr($file, 0, -4) . ".dll.a";

							echo $echoprefix . " Running '" . $cmd . "'...\n";

							$errorfilename = $pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/package_mingw_dlltool_" . $arch . "_" . substr($file, 0, -4) . "_error.log";
							$result = RunCommand($cmd, $errorfilename, $destdir, $baseenv);
							if ($result === false)  CLI::DisplayError($echoprefix . " Failed to start process.");

							file_put_contents($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/package_mingw_dlltool_" . $arch . "_" . substr($file, 0, -4) . "_out.log", $result);

							$filename = $mingwlibdir . "/" . substr($file, 0, -4) . ".dll.a";
							if (!file_exists($filename))  CLI::DisplayError($echoprefix . " Unable to generate '" . $filename . "'.");
						}
					}

					closedir($dir);
				}
			}

			// Run Inno Setup compiler.
			if (isset($archinfo["package"]["inno_setup_dir"]) && $archinfo["package"]["inno_setup_dir"] !== "")
			{
				echo $echoprefix . " Running Inno Setup compiler...\n";

				$dir = opendir($pathmap["[[INSTALLERS_ARCH_DIR]]"]);
				if ($dir)
				{
					while (($file = readdir($dir)) !== false)
					{
						if (substr($file, -4) === ".iss")
						{
							$cmd = str_replace(array_keys($pathmap), array_values($pathmap), $archinfo["package"]["inno_setup_dir"] . "/iscc.exe");
							$cmd = escapeshellarg(str_replace("/", "\\", $cmd));

							$cmd .= " " . escapeshellarg(str_replace("/", "\\", $pathmap["[[INSTALLERS_ARCH_DIR]]"] . "/" . $file));

							echo $echoprefix . " Running '" . $cmd . "'...\n";

							$errorfilename = $pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/package_inno_setup_" . $arch . "_" . substr($file, 0, -4) . "_error.log";
							$result = RunCommand($cmd, $errorfilename, $destdir, $baseenv);
							if ($result === false)  CLI::DisplayError($echoprefix . " Failed to start process.");

							file_put_contents($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/package_inno_setup_" . $arch . "_" . substr($file, 0, -4) . "_out.log", $result);

							// Verify that the EXE was created by looking for the OutputBaseFilename.
							$filename = false;
							$lines = explode("\n", file_get_contents($pathmap["[[INSTALLERS_ARCH_DIR]]"] . "/" . $file));
							foreach ($lines as $line)
							{
								$line = trim($line);
								$pos = strpos($line, "=");
								if ($pos !== false && trim(substr($line, 0, $pos)) === "OutputBaseFilename")  $filename = $destdir . "/Output/" . trim(substr($line, $pos + 1)) . ".exe";
							}

							if (!file_exists($filename))  CLI::DisplayError($echoprefix . " Unable to generate '" . $filename . "'.");
						}
					}

					closedir($dir);
				}
			}

			// Run Wix toolset compiler.
			if (isset($archinfo["package"]["wix_toolset_dir"]) && $archinfo["package"]["wix_toolset_dir"] !== "" && isset($archinfo["package"]["wix_toolset_target"]))
			{
				echo $echoprefix . " Running Wix toolset compiler...\n";

				$dir = opendir($pathmap["[[INSTALLERS_ARCH_DIR]]"]);
				if ($dir)
				{
					while (($file = readdir($dir)) !== false)
					{
						if (substr($file, -4) === ".wxs")
						{
							// Extract SourceSetupFile.
							$basefilename = false;
							$lines = explode("\n", file_get_contents($pathmap["[[INSTALLERS_ARCH_DIR]]"] . "/" . $file));
							foreach ($lines as $line)
							{
								$line = trim($line);

								$pos = strpos($line, " SourceSetupFile ");
								if ($pos !== false)
								{
									$basefilename = substr($line, strpos($line, "\"", $pos) + 1);
									$basefilename = substr($basefilename, 0, strrpos($basefilename, "\"") - 4);
								}
							}

							if ($basefilename === false)  CLI::DisplayError($echoprefix . " Unable to find 'SourceSetupFile' in '" . $pathmap["[[INSTALLERS_ARCH_DIR]]"] . "/" . $file . "'.");

							$wixobjfilename = $destdir . "/Output/" . $basefilename . ".wixobj";
							$wixpdbfilename = $destdir . "/Output/" . $basefilename . ".wixpdb";
							$msifilename = $destdir . "/Output/" . $basefilename . ".msi";


							// Run candle.exe to output .wixobj.
							$cmd = str_replace(array_keys($pathmap), array_values($pathmap), $archinfo["package"]["wix_toolset_dir"] . "/candle.exe");
							$cmd = escapeshellarg(str_replace("/", "\\", $cmd));

							$cmd .= " " . $archinfo["package"]["wix_toolset_target"] . " -o " . escapeshellarg(str_replace("/", "\\", $wixobjfilename)) . " " . escapeshellarg(str_replace("/", "\\", $pathmap["[[INSTALLERS_ARCH_DIR]]"] . "/" . $file));

							echo $echoprefix . " Running '" . $cmd . "'...\n";

							$errorfilename = $pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/package_wix_toolset_candle_" . $arch . "_" . substr($file, 0, -4) . "_error.log";
							$result = RunCommand($cmd, $errorfilename, $destdir, $baseenv);
							if ($result === false)  CLI::DisplayError($echoprefix . " Failed to start process.");

							file_put_contents($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/package_wix_toolset_candle_" . $arch . "_" . substr($file, 0, -4) . "_out.log", $result);

							// Verify that the .wixobj file was created.
							if (!file_exists($wixobjfilename))  CLI::DisplayError($echoprefix . " Unable to generate '" . $wixobjfilename . "'.");


							// Run light.exe to output .msi.
							$cmd = str_replace(array_keys($pathmap), array_values($pathmap), $archinfo["package"]["wix_toolset_dir"] . "/light.exe");
							$cmd = escapeshellarg(str_replace("/", "\\", $cmd));

							$cmd .= " -b " . escapeshellarg(str_replace("/", "\\", $destdir . "/Output")) . " -ext WixUtilExtension.dll -out " . escapeshellarg(str_replace("/", "\\", $msifilename)) . " " . escapeshellarg(str_replace("/", "\\", $wixobjfilename));

							echo $echoprefix . " Running '" . $cmd . "'...\n";

							$errorfilename = $pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/package_wix_toolset_light_" . $arch . "_" . substr($file, 0, -4) . "_error.log";
							$result = RunCommand($cmd, $errorfilename, $destdir, $baseenv);
							if ($result === false)  CLI::DisplayError($echoprefix . " Failed to start process.");

							file_put_contents($pathmap["[[BUILD_OUTPUT_DIR]]"] . "/logs/package_wix_toolset_light_" . $arch . "_" . substr($file, 0, -4) . "_out.log", $result);

							// Verify that the MSI was created.
							if (!file_exists($msifilename))  CLI::DisplayError($echoprefix . " Unable to generate '" . $msifilename . "'.");

							@unlink($wixobjfilename);
							@unlink($wixpdbfilename);
						}
					}

					closedir($dir);
				}
			}
		}

		// All finished.
		$ts2 = time();
		$secs = $ts2 - $startts;
		$mins = (int)($secs / 60);
		$secs %= 60;

		echo $echoprefix . " Finished building and packaging at " . date("Y-m-d H:i:s") . ".  Total time:  " . $mins . " min " . $secs . " sec\n";
	}
?>