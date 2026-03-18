import sys

file1 = r"c:\PRJ\MOW\Misc\AFE4490\Pulsioximeter_test_PABLO\Pulsioximeter_test\src\Protocentral_spo2_algorithm.cpp"
file2 = r"c:\PRJ\MOW\Misc\AFE4490\Pulsioximeter_test_PABLO\Pulsioximeter_test\.pio\libdeps\in3ator_V15\ProtoCentral AFE4490 PPG and SpO2 boards library\src\Protocentral_spo2_algorithm.cpp"

with open(file1, 'r', encoding='utf-8', errors='ignore') as f1, open(file2, 'r', encoding='utf-8', errors='ignore') as f2:
    lines1 = f1.readlines()
    lines2 = f2.readlines()

    if len(lines1) != len(lines2):
        print(f"Different number of lines: {len(lines1)} vs {len(lines2)}")
    
    for i, (l1, l2) in enumerate(zip(lines1, lines2)):
        if l1.strip() != l2.strip():
            print(f"Difference at line {i+1}:")
            print(f"File1: {repr(l1)}")
            print(f"File2: {repr(l2)}")
            break
    else:
        if len(lines1) == len(lines2):
            print("Files are identical in content (ignoring whitespace/line endings)")
        else:
            print("Files match up to the end of the shorter file.")
