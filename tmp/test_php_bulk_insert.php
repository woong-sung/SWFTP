<?php
class StubDB {
    public $calls = array();
    function executeQry($sql, $params) {
        $this->calls[] = array($sql, $params);
        return true;
    }
}
function check($condition, $message) {
    if (!$condition) { throw new Exception($message); }
}
function runCase($type, $rows) {
    $db = new StubDB();
    $_rightArray = $rows;
    $_jojik_type = $type;
    $_manager_code = 'manager';
    $_SESSION = array('manager_code' => 'actor');
    $bubinID = 'original-company';
    $loop = array();
    eval(file_get_contents(__DIR__ . '/php_bulk_insert_block.txt'));
    check(count($db->calls) === (count($rows) ? 1 : 0), 'query count');
    if (!$rows) { return; }
    list($sql, $params) = $db->calls[0];
    preg_match_all('/:[a-z_]+[0-9]+/', $sql, $matches);
    check(count($matches[0]) === count($rows) * 6, 'placeholder count');
    check(count(array_unique($matches[0])) === count($matches[0]), 'unique placeholders');
    check(count($params) === count($matches[0]), 'parameter count');
    foreach ($matches[0] as $placeholder) {
        check(array_key_exists(substr($placeholder, 1), $params), 'bound parameter');
    }
    $i = 0;
    foreach ($rows as $row) {
        check($params['company_id_' . $i] === ($type === 'B' ? $row['company_id'] : 'original-company'), 'company id');
        check($params['company_no_' . $i] === ($type === 'B' ? '00000000' : $row['company_no']), 'company no');
        check($params['saupjang_no_' . $i] === ($row['saupjang_no'] ? $row['saupjang_no'] : '000'), 'saupjang default');
        check($params['station_no_' . $i] === ($row['station_no'] ? $row['station_no'] : '0000'), 'station default');
        check($params['target_manager_' . $i] === 'manager', 'manager');
        check($params['actor_code_' . $i] === 'actor', 'actor');
        $i++;
    }
    check(count($loop) === 1, 'query log');
}
$rows = array(
    'first' => array('company_id' => 'a', 'company_no' => '123', 'saupjang_no' => '', 'station_no' => ''),
    'second' => array('company_id' => "b'quote", 'company_no' => '456', 'saupjang_no' => '001', 'station_no' => '0002')
);
runCase('A', array());
runCase('A', array($rows['first']));
runCase('A', $rows);
runCase('B', $rows);
echo "PASS: empty, single, multiple, B-type, defaults and unique bindings\n";
